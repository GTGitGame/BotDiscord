import discord
import os
import asyncio
import datetime
import psycopg2
import feedparser
from dotenv import load_dotenv
from keep_alive import keep_alive  # Import du fichier qu'on vient de créer
from discord.ext import commands
keep_alive()  # Lance le serveur web
load_dotenv()
check_youtube.start()

# --- CONFIGURATION ET INITIALISATION BDD ---
DATABASE_URL = os.getenv('DATABASE_URL')

def init_db():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    # Table des avertissements
    cur.execute('''CREATE TABLE IF NOT EXISTS warnings (user_id TEXT PRIMARY KEY, count INTEGER DEFAULT 0)''')
    # Table de l'historique des bans
    cur.execute('''CREATE TABLE IF NOT EXISTS bans (id SERIAL PRIMARY KEY, user_name TEXT, reason TEXT, proof TEXT, date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    # Table des mots interdits (ta liste noire)
    cur.execute('''CREATE TABLE IF NOT EXISTS banned_words (word TEXT PRIMARY KEY)''')
    conn.commit()
    cur.close()
    conn.close()

# On appelle la fonction IMMÉDIATEMENT pour que les tables soient prêtes
init_db()


print("Lancement du  bot...")
bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

@bot.event
async def on_ready():
    print("Bat allumé !")
    #synchroniser les commandes
    try:
        #sync (synced nom modifiable sans problème ATTENTION: Ne pas oubliez de remplacer dans ce cas.)
        synced = await bot.tree.sync()
        print(f"Commandes slash synchronisées : {len(synced)}")
    except Exception as e:
        print(e)

# Configuration
YOUTUBE_CHANNEL_ID = "UC17HUcSwYnE7b5XxEWLqhRw" # Votre ID de chaîne
DISCORD_CHANNEL_ID = 1497974787719561337 # L'ID du salon "vidéos"
LAST_VIDEO_ID = None
ROLE_ID = 1499122462133059659 

@tasks.loop(minutes=10)
async def check_youtube():
    global LAST_VIDEO_ID
    url = f"https://youtube.com{YOUTUBE_CHANNEL_ID}"
    feed = feedparser.parse(url)
    
    if not feed.entries:
        return

    latest_video = feed.entries[0]
    video_id = latest_video.yt_videoid
    video_url = latest_video.link

    # Si c'est une nouvelle vidéo
    if LAST_VIDEO_ID != video_id:
        if LAST_VIDEO_ID is not None: # Évite d'envoyer la dernière vidéo au démarrage
            channel = bot.get_channel(DISCORD_CHANNEL_ID)
            await channel.send(f"Salut Tout le monde <@&{ROLE_ID}> ! 👋 Une nouvelle vidéo de [GTGaming](https://www.youtube.com/@gtgame24) est disponible allez donc la voir ! **{latest_video.title}**\n{video_url} Bon visionnage !")
        
        LAST_VIDEO_ID = video_id

# Dictionnaire : "ÉMOJI": ID_DU_RÔLE
REACTION_ROLES = {
    "🔴": 1499122462133059659,  # Notifications YouTube
    "🎮": 1499123914713071736,  # Annonces Gaming 
    "📢": 1499124046787510344,  # Annonces Générales 
    "💻": 1499115980813504512
}

@bot.event
async def on_raw_reaction_add(payload):
    # On vérifie si c'est le bon message
    if payload.message_id != CHOICE_MESSAGE_ID:
        return

    # On cherche si l'émoji cliqué est dans notre dictionnaire
    emoji_name = str(payload.emoji)
    if emoji_name in REACTION_ROLES:
        guild = bot.get_guild(payload.guild_id)
        role_id = REACTION_ROLES[emoji_name]
        role = guild.get_role(role_id)
        
        if role:
            await payload.member.add_roles(role)
            print(f"Rôle {role.name} ajouté à {payload.member}")

@bot.event
async def on_raw_reaction_remove(payload):
    # Même logique pour retirer le rôle
    if payload.message_id != CHOICE_MESSAGE_ID:
        return

    emoji_name = str(payload.emoji)
    if emoji_name in REACTION_ROLES:
        guild = bot.get_guild(payload.guild_id)
        role_id = REACTION_ROLES[emoji_name]
        role = guild.get_role(role_id)
        member = await guild.fetch_member(payload.user_id)
        
        if role and member:
            await member.remove_roles(role)
            print(f"Rôle {role.name} retiré à {member}")

@bot.command()
async def setup_roles(ctx):
    embed = discord.Embed(description="Réagis ici pour tes rôles...")
    message = await ctx.send(embed=embed)
    
    # On met à jour l'ID global automatiquement pour ne pas avoir à le copier-coller
    global CHOICE_MESSAGE_ID
    CHOICE_MESSAGE_ID = message.id 
    
    for emoji in REACTION_ROLES.keys():
        await message.add_reaction(emoji)

# L'ID du message où les gens doivent cliquer
CHOICE_MESSAGE_ID = 1499125527313776692

@bot.command()
@commands.has_permissions(administrator=True)
async def setup_roles(ctx):
    embed = discord.Embed(
        title="Choisis tes notifications",
        description="Réagis avec les émojis correspondants pour obtenir tes rôles :\n\n"
                    "🔴 : Notifications YouTube\n"
                    "🎮 : Actu Gaming\n"
                    "📢 : Annonces importantes\n"
                    "💻 : Hack Switch + Mods, etc",
        color=discord.Color.blue()
    )
    
    message = await ctx.send(embed=embed)
    
    # Le bot ajoute automatiquement les émojis pour que les gens n'aient qu'à cliquer
    for emoji in REACTION_ROLES.keys():
        await message.add_reaction(emoji)
    
    print(f"Nouveau MESSAGE_ID à copier dans le code : {message.id}")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot: return

    # --- 1. RÉCUPÉRER LES INSULTES DEPUIS LA BDD ---
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    cur.execute("SELECT word FROM banned_words")
    # On transforme le résultat en une liste simple de mots
    mots_interdits = [row[0] for row in cur.fetchall()]
    
    content = message.content.lower()

    # --- 2. VÉRIFICATION ---
    if any(word in content for word in mots_interdits):
        await message.delete()
        user_id = str(message.author.id)
        
        # --- 3. GESTION DES WARNS DANS LA BDD ---
        cur.execute('''INSERT INTO warnings (user_id, count) VALUES (%s, 1)
                       ON CONFLICT (user_id) DO UPDATE SET count = warnings.count + 1 
                       RETURNING count''', (user_id,))
        
        count = cur.fetchone()[0]
        
        if count >= 3:
            # Enregistrement du ban et reset
            cur.execute("INSERT INTO bans (user_name, reason, proof) VALUES (%s, %s, %s)", 
                        (message.author.name, "3 avertissements", message.content))
            cur.execute("DELETE FROM warnings WHERE user_id = %s", (user_id,))
            conn.commit()
            
            await message.author.ban(reason="3 avertissements (Automod)")
            await message.channel.send(f"🚨 {message.author.mention} banni pour accumulation d'infractions.")
        else:
            conn.commit()
            await message.channel.send(f"⚠️ {message.author.mention}, attention ! ({count}/3)")
    
    cur.close()
    conn.close()
    await bot.process_commands(message)

@bot.tree.command(name="test", description="Test des embeds")
async def test_embed(interaction: discord.Interaction, member: discord.Member):
    embed = discord.Embed(
        title="Test Title",
        description="Description de l'embed",
        color=discord.Color.blue()
    )
    #embed.(...) field (paragraphe), footer (bas de message), image (inclure une image),
    embed.add_field(name="Python", value="Apprendre le python en s'amusant", inline=False)
    embed.add_field(name="Web", value="Apprendre le web en s'amusant", inline=False)
    embed.set_footer(text="Bas de message")
    embed.set_image(url="https://pixabay.com/fr/images/download/muhammadsaqii786-youtube-6621791_1920.jpg")

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="warnguy", description="Alerter une personne")
@discord.app_commands.default_permissions(ban_members=True) #Permission/rôle Requis(e) (ex: Modérateur)
async def warnguy(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.send_message("Alerte envoyé !")
    await member.send("Tu as reçu une alerte")

@bot.tree.command(name="banguy", description="Alerter une personne")
@discord.app_commands.default_permissions(ban_members=True)
async def banguy(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.send_message("Ban envoyé !")
    await member.ban(reason="Tu n'es pas abonné")
    await member.send("Tu as été Banni")

@bot.tree.command(name="youtube", description="Affiche ma chaine youtube")
async def youtube(interaction: discord.Interaction):
    await interaction.response.send_message("Voici le lien de ma chaine Youtube: https://www.youtube.com/@GTGame24")

@bot.tree.command(name="isadraw", description="Affiche les Réseaux de la chaîne IsaDraw")
async def test_embed(interaction: discord.Interaction, member: discord.Member):
    embed = discord.Embed(
        title="IsaDraw",
        description="Découvrez les réseaux sociaux de IsaDraw n'hésitez pas à le suivre 😉!",
    )
    #embed.(...) field (paragraphe), footer (bas de message), image (inclure une image),
    embed.add_field(name="Youtube", value=" [Isa Draw](https://www.youtube.com/@Isa_Draw12)")
    embed.add_field(name="Instagram", value=" [isadraw12](https://www.instagram.com/isadraw12)")
    embed.set_image(url="https://yt3.googleusercontent.com/9pdUfE3u2IG761i4xxNTWoncrOd2CtFQ6OIGxpDSGLID7sz-dKUVZdhYr_ftyGDvTo8Ke_yMhzA=s160-c-k-c0x00ffffff-no-rj")
    embed.set_footer(text="Chaîne de Dessin ✏️ !")

    await interaction.response.send_message(embed=embed)

@bot.event
async def on_member_join(member):
    # Chercher un canal nommé 'bienvenue' dans la guild où le membre a rejoint
    channel = discord.utils.get(member.guild.text_channels, name='👋bienvenue👋')
    if channel:
        # Envoyer un message de bienvenue personnalisé
        await channel.send(f'Bienvenue sur le serveur, {member.mention} ! 🎉')

@bot.tree.command(name="hack_switch", description="Retrouvez l'endroit où se trouve les docs + Tuto sur hack_Switch")
async def hack_switch(interaction: discord.Interaction):
    # Récupérer le channel par ID
    channel = bot.get_channel(1497967551496458322)

    if channel is None:
        await interaction.response.send_message("Le salon spécifié est introuvable.", ephemeral=True)
        return

    await interaction.response.send_message(
        f"Salut {interaction.user.mention} ! Les fichiers/dossiers ainsi que les Tutos se trouvent dans le salon {channel.mention}. "
        "⚠️ Attention: Rappel: A suivre étape par étape sinon risque de Brick (Rendre la console Inutilisable) ⚠️ A vos risques et périls ..."
    )

@bot.tree.command(name="add_insulte", description="Ajouter un mot à la liste noire")
@discord.app_commands.default_permissions(administrator=True)
async def add_insulte(interaction: discord.Interaction, mot: str):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO banned_words (word) VALUES (%s) ON CONFLICT DO NOTHING", (mot.lower(),))
        conn.commit()
        await interaction.response.send_message(f"✅ Le mot `{mot}` est maintenant interdit.")
    except Exception as e:
        await interaction.response.send_message(f"Erreur : {e}")
    finally:
        cur.close()
        conn.close()

@bot.tree.command(name="verification", description="Une commande pour obtenir le grade de membre Certifié")
async def verif(interaction: discord.Interaction, member: discord.Member):
    role_id = 1497970323096735785
    role_mention = f"<@&{role_id}>"

    # Envoyer un message d'information dans le canal
    msg = await interaction.channel.send(
        f"{member.mention}, un modérateur va vérifier ta demande. Réagissez avec ✅ ou ❌."
    )
    # Ajouter les réactions pour la modération
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")

    # Répondre à l'utilisateur que le message a été envoyé
    await interaction.response.send_message(
        f"Salut {interaction.user.mention} ! Pour devenir {role_mention} tu dois répondre à ce questionnaire. En cas d'acceptation, tu recevras un MP alors sois à l'affût 😉! "
        "⚠️ Attention: une fois certifié, la modération de ton compte sera réduite mais si tu enfreins une règle, ce sera tolérance zéro (Ban jusqu'à nouvelle ordre!). ⚠️",
        ephemeral=True
    )


@bot.event
async def on_reaction_add(reaction, user):
    # Ignorer les réactions du bot lui-même
    if user.bot:
        return

    # Vérifier que l'utilisateur est modérateur (exemple avec un rôle nommé "Modérateur")
    mod_role = discord.utils.get(user.guild.roles, name="Modérateur")
    if mod_role not in user.roles:
        return

    # Vérifier que la réaction est sur un message du bot (pour éviter de traiter toutes les réactions)
    if reaction.message.author != bot.user:
        return

    # Vérifier que le message contient au moins une mention (le membre à notifier)
    if not reaction.message.mentions:
        return

    member_to_notify = reaction.message.mentions[0]

    # Récupérer le rôle à attribuer (exemple : rôle "Certifié")
    role_to_add = user.guild.get_role(1497970323096735785) # Utilise l'ID que tu as déjà

    if str(reaction.emoji) == "✅":
        # Envoyer MP de bienvenue
        try:
            await member_to_notify.send("Bienvenue ! Votre commande a été acceptée.")
        except discord.Forbidden:
            print(f"Impossible d'envoyer un MP à {member_to_notify}")

        # Ajouter le rôle "Certifié" au membre
        if role_to_add:
            try:
                await member_to_notify.add_roles(role_to_add)
            except discord.Forbidden:
                print(f"Impossible d'ajouter le rôle à {member_to_notify}")
            except Exception as e:
                print(f"Erreur lors de l'ajout du rôle : {e}")

        elif str(reaction.emoji) == "❌":
            try:
                await member_to_notify.send("Désolé, votre demande a été refusée.")
            except discord.Forbidden:
                print(f"Erreur refus: {e}")

# Dictionnaire pour stocker les avertissements {user_id: nombre_davertissements}

# Liste des mots interdits (à compléter selon tes règles)

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # 1. On vérifie d'abord s'il y a une infraction
    content = message.content.lower()
    if any(word in content for word in BANNED_WORDS):
        await message.delete() # Optionnel : supprimer le message
        
        user_id = str(message.author.id) # Définition de l'ID
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
            
        cur.execute('''INSERT INTO warnings (user_id, count) VALUES (%s, 1)
                           ON CONFLICT (user_id) DO UPDATE SET count = warnings.count + 1 
                           RETURNING count''', (user_id,))
        count = cur.fetchone()[0] # Le [0] est important pour avoir le chiffre
            
        if count >= 3:
            cur.execute("INSERT INTO bans (user_name, reason, proof) VALUES (%s, %s, %s)", 
                        (message.author.name, "3 avertissements", message.content))
            cur.execute("DELETE FROM warnings WHERE user_id = %s", (user_id,))
            conn.commit()
            await message.author.ban(reason="3 avertissements (Automod)")
            await message.channel.send(f"🚨 {message.author.mention} banni (3/3 infractions).")
        else:
            conn.commit()
            await message.channel.send(f"⚠️ {message.author.mention}, attention ! ({count}/3)")
            
        cur.close()
        conn.close()

    # Important pour les commandes "!"
    await bot.process_commands(message)


@bot.tree.command(name="tempban", description="Bannir un membre temporairement")
@discord.app_commands.default_permissions(ban_members=True) # Réservé au Staff
async def tempban(interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "Non spécifiée"):
    await interaction.response.send_message(f"🔨 {member.mention} a été banni pour {minutes} minutes. Raison : {reason}")
    
    try:
        await member.send(f"Tu as été banni de {interaction.guild.name} pendant {minutes} minutes pour : {reason}")
        await member.ban(reason=reason)
        
        # Attendre la durée avant de débannir
        await asyncio.sleep(minutes * 60)
        
        await interaction.guild.unban(member)
        print(f"{member.name} a été débanni après {minutes} minutes.")
    except Exception as e:
        print(f"Erreur lors du tempban : {e}")

@bot.tree.command(name="ban_history", description="Voir l'historique des bannissements")
@discord.app_commands.default_permissions(administrator=True)
async def history(interaction: discord.Interaction):
    data = load_data()
    history = data["bans_history"]
    
    if not history:
        return await interaction.response.send_message("L'historique est vide.", ephemeral=True)
    
    embed = discord.Embed(title="📜 Historique des Bans", color=discord.Color.red())
    # On affiche les 5 derniers pour ne pas surcharger
    for entry in history[-5:]:
        embed.add_field(
            name=f"Utilisateur : {entry['user']}",
            value=f"📅 Date: {entry['date']}\n📝 Raison: {entry['reason']}\n📂 Preuve: {entry['proof']}",
            inline=False
        )
    await interaction.response.send_message(embed=embed)

# --- GESTION DES ERREURS DE COMMANDES ---
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.CheckFailure):
        await interaction.response.send_message("Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True)
    else:
        print(f"Erreur : {error}")

bot.run(os.getenv('DISCORD_TOKEN'))