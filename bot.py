import discord
import os
import asyncio
import datetime
import psycopg2
import feedparser
from dotenv import load_dotenv
from keep_alive import keep_alive
from discord.ext import commands, tasks
from discord.ui import Button, View

keep_alive()
load_dotenv()

# --- CONFIGURATION GENERALES & IDENTIFIANTS ---
DATABASE_URL = os.getenv('DATABASE_URL')

YOUTUBE_CHANNEL_ID = "UC17HUcSwYnE7b5XxEWLqhRw"
DISCORD_CHANNEL_ID = 1497974787719561337      # Salon "vidéos"
REGLEMENT_CHANNEL_ID = 1536738321240293479    # Remplace par l'ID réel du salon règlement
MOD_LOG_CHANNEL_ID = 1536769906295443467      # Remplace par l'ID réel du salon de modération/fondateur

ROLE_ID = 1499122462133059659                 # Rôle Notif YouTube
CHOICE_MESSAGE_ID = 1499125527313776692       # ID du message pour les Reaction Roles
VERIF_ROLE_ID = 1497970323096735785           # Rôle Membre Certifié

LAST_VIDEO_ID = None

# Nom exact du salon vocal déclencheur sur Discord
TRIGGER_VOICE_NAME = "-- Créé ton Vocal privé Ici --"

# Liste pour suivre les salons vocaux temporaires créés
temp_voice_channels = set()

# Mots obscènes/interdits par défaut (complétés par la BDD)
OBSCENE_WORDS = ["connasse", "putain", "porno", "hentai", "fuck", "salope", "connard", "foutre", "bitte", "teub", "con", "conne"]

# Texte officiel du Règlement
REGLEMENT_TEXT = """📜 **RÈGLEMENT DU SERVEUR**

1️⃣ **Respect & Politesse** : Pas d'insultes, de propos haineux, racistes ou obscènes.
2️⃣ **Pas de Spam / Pub** : Le spam et les liens non autorisés sont strictement interdits.
3️⃣ **Contenu approprié** : Gardez les échanges adaptés à tous les publics (pas de NSFW/contenu explicite).
4️⃣ **Écoute de l'équipe** : Respectez les décisions des modérateurs et des administrateurs.

⚠️ *En cas d'accumulation de 3 avertissements, une demande de bannissement sera soumise à l'équipe de modération.*"""

# Dictionnaire Réaction -> Rôle
REACTION_ROLES = {
    "🔴": 1499122462133059659,  # Notifications YouTube
    "🎮": 1499123914713071736,  # Annonces Gaming 
    "📢": 1499124046787510344,  # Annonces Générales 
    "💻": 1499115980813504512   # Hack Switch + Mods
}

# --- INITIALISATION BDD ---
def init_db():
    if not DATABASE_URL:
        print("⚠️ DATABASE_URL non définie.")
        return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        # Création de la table warnings avec enregistrement de la date de mise à jour (updated_at)
        cur.execute('''CREATE TABLE IF NOT EXISTS warnings (
            user_id TEXT PRIMARY KEY, 
            count INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS bans (
            id SERIAL PRIMARY KEY, 
            user_name TEXT, 
            reason TEXT, 
            proof TEXT, 
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS banned_words (word TEXT PRIMARY KEY)''')
        conn.commit()
        cur.close()
        conn.close()
        print("✅ Base de données initialisée avec succès.")
    except Exception as e:
        print(f"⚠️ Erreur BDD : {e}")

init_db()

# --- INITIALISATION DU BOT ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# --- VUE DE MODÉRATION (DEMANDE DE BAN POUR 3 WARNS) ---
class BanRequestView(View):
    def __init__(self, target_member: discord.Member, reason: str):
        super().__init__(timeout=None)
        self.target_member = target_member
        self.reason = reason

    @discord.ui.button(label="🔨 Bannir le membre", style=discord.ButtonStyle.danger)
    async def confirm_ban(self, interaction: discord.Interaction, button: Button):
        if not interaction.user.guild_permissions.ban_members:
            return await interaction.response.send_message("Tu n'as pas la permission d'exécuter cette action.", ephemeral=True)
        
        await self.target_member.ban(reason=f"3 Avertissements - Validé par {interaction.user.name}")
        await interaction.response.send_message(f"✅ {self.target_member.mention} a été banni du serveur par {interaction.user.mention}.")
        self.stop()

    @discord.ui.button(label="❌ Réinitialiser avertissements", style=discord.ButtonStyle.secondary)
    async def reset_warns(self, interaction: discord.Interaction, button: Button):
        if not interaction.user.guild_permissions.ban_members:
            return await interaction.response.send_message("Tu n'as pas la permission d'exécuter cette action.", ephemeral=True)

        if DATABASE_URL:
            conn = psycopg2.connect(DATABASE_URL)
            cur = conn.cursor()
            cur.execute("DELETE FROM warnings WHERE user_id = %s", (str(self.target_member.id),))
            conn.commit()
            cur.close()
            conn.close()

        await interaction.response.send_message(f"🔄 Avertissements réinitialisés pour {self.target_member.mention}.")
        self.stop()

# --- ÉVÉNEMENT ON_READY ---
@bot.event
async def on_ready():
    print("Bot allumé !")
    check_youtube.start()
    clean_expired_warns.start()
    await update_reglement()
    try:
        synced = await bot.tree.sync()
        print(f"Commandes slash synchronisées : {len(synced)}")
    except Exception as e:
        print(f"Erreur de synchronisation : {e}")

# --- GESTION AUTOMATIQUE DU RÈGLEMENT ---
async def update_reglement():
    channel = bot.get_channel(REGLEMENT_CHANNEL_ID)
    if not channel:
        return

    async for message in channel.history(limit=10):
        if message.author == bot.user:
            if message.content == REGLEMENT_TEXT:
                return  # Règlement déjà affiché et à jour
            else:
                await message.delete()  # Ancienne version supprimée

    # Publication du nouveau règlement s'il est absent ou a été modifié
    await channel.send(REGLEMENT_TEXT)

# --- VERIFICATION DES NOUVELLES VIDÉOS & SHORTS YOUTUBE ---
@tasks.loop(minutes=10)
async def check_youtube():
    global LAST_VIDEO_ID
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}"
    feed = feedparser.parse(url)
    
    if not feed.entries:
        return

    latest_video = feed.entries[0]
    video_id = latest_video.get('yt_videoid', latest_video.id)
    video_url = latest_video.link

    if LAST_VIDEO_ID != video_id:
        if LAST_VIDEO_ID is not None:
            channel = bot.get_channel(DISCORD_CHANNEL_ID)
            if channel:
                is_short = "/shorts/" in video_url or "short" in latest_video.title.lower()
                content_type = "📱 **Nouveau Short**" if is_short else "🎬 **Nouvelle Vidéo**"
                
                await channel.send(
                    f"Salut Tout le monde <@&{ROLE_ID}> ! 👋 {content_type} de GTGaming est disponible ! **{latest_video.title}**\n{video_url}"
                )
        LAST_VIDEO_ID = video_id

# --- EXPIRATION AUTOMATIQUE DES WARNS (Chaque jour) ---
@tasks.loop(hours=24)
async def clean_expired_warns():
    if not DATABASE_URL:
        return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        # Réduit le nombre de warns de 1 pour les utilisateurs dont le dernier warn date de plus de 30 jours
        cur.execute("""
            UPDATE warnings 
            SET count = count - 1, updated_at = CURRENT_TIMESTAMP 
            WHERE updated_at < CURRENT_TIMESTAMP - INTERVAL '30 days' AND count > 0
        """)
        # Supprime les entrées qui sont tombées à 0 warn
        cur.execute("DELETE FROM warnings WHERE count <= 0")
        conn.commit()
        cur.close()
        conn.close()
        print("🧹 Vérification des avertissements expirés effectuée.")
    except Exception as e:
        print(f"⚠️ Erreur lors du nettoyage des warns : {e}")

# --- GESTION DES VOCAUX PRIVÉS TEMPORAIRES ---
@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    # 1. Création du vocal privé quand un membre rejoint le salon déclencheur
    if after.channel and after.channel.name.lower() == TRIGGER_VOICE_NAME.lower():
        guild = member.guild
        category = after.channel.category

        # Permissions : Salon visible par tous (@everyone), mais seul le créateur peut se connecter / inviter
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=False),
            member: discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True, manage_channels=True)
        }

        # Création du salon vocal
        new_channel = await guild.create_voice_channel(
            name=f"🔒 Salon privé de {member.display_name}",
            category=category,
            overwrites=overwrites
        )

        temp_voice_channels.add(new_channel.id)

        # Déplacement automatique du créateur dans son salon
        await member.move_to(new_channel)

    # 2. Suppression automatique lorsque le salon temporaire devient vide
    if before.channel and (before.channel.id in temp_voice_channels or before.channel.name.startswith("🔒 Salon de")):
        if len(before.channel.members) == 0:
            temp_voice_channels.discard(before.channel.id)
            try:
                await before.channel.delete(reason="Vocal privé temporaire vide.")
            except discord.NotFound:
                pass

# --- GESTION DES REACTION ROLES (RAW EVENTS) ---
@bot.event
async def on_raw_reaction_add(payload):
    if payload.message_id != CHOICE_MESSAGE_ID:
        return

    emoji_name = str(payload.emoji)
    if emoji_name in REACTION_ROLES:
        guild = bot.get_guild(payload.guild_id)
        role_id = REACTION_ROLES[emoji_name]
        role = guild.get_role(role_id)
        
        if role and payload.member:
            await payload.member.add_roles(role)
            print(f"Rôle {role.name} ajouté à {payload.member}")

@bot.event
async def on_raw_reaction_remove(payload):
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

# --- COMMANDES PREFIX (!) ---
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
    
    for emoji in REACTION_ROLES.keys():
        await message.add_reaction(emoji)
    
    print(f"Nouveau MESSAGE_ID à copier dans le code : {message.id}")

# --- AUTO-MODÉRATION SUR LES MESSAGES ---
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    content = message.content.lower()

    # Récupération de la liste des mots interdits
    mots_interdits = OBSCENE_WORDS.copy()
    if DATABASE_URL:
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cur = conn.cursor()
            cur.execute("SELECT word FROM banned_words")
            mots_interdits.extend([row[0] for row in cur.fetchall()])
            cur.close()
            conn.close()
        except Exception as e:
            print(f"Erreur BDD : {e}")

    # Détection de mot interdit
    if any(word in content for word in mots_interdits):
        await message.delete()
        user_id = str(message.author.id)
        
        count = 1
        if DATABASE_URL:
            try:
                conn = psycopg2.connect(DATABASE_URL)
                cur = conn.cursor()
                # Met à jour le compteur ET la date de dernier avertissement (updated_at)
                cur.execute('''INSERT INTO warnings (user_id, count, updated_at) 
                               VALUES (%s, 1, CURRENT_TIMESTAMP)
                               ON CONFLICT (user_id) DO UPDATE 
                               SET count = warnings.count + 1, updated_at = CURRENT_TIMESTAMP
                               RETURNING count''', (user_id,))
                count = cur.fetchone()[0]
                conn.commit()
                cur.close()
                conn.close()
            except Exception as e:
                print(f"Erreur BDD lors du warn : {e}")

        # Traitement selon le nombre d'avertissements
        if count >= 3:
            mod_channel = bot.get_channel(MOD_LOG_CHANNEL_ID)
            if mod_channel:
                embed = discord.Embed(
                    title="🚨 Demande de Bannissement requise",
                    description=f"L'utilisateur {message.author.mention} a atteint **3 avertissements**.",
                    color=discord.Color.red()
                )
                embed.add_field(name="Dernier message suspect", value=f"`{message.content}`")
                view = BanRequestView(target_member=message.author, reason="3 avertissements (AutoMod)")
                await mod_channel.send(embed=embed, view=view)

            await message.channel.send(f"🚨 {message.author.mention}, vous avez accumulé 3 avertissements. Une demande de bannissement a été transmise à la modération.")
        else:
            await message.channel.send(f"⚠️ {message.author.mention}, attention aux propos tenus ! ({count}/3)", delete_after=10)

    await bot.process_commands(message)

# --- COMMANDES SLASH (TREE) ---
@bot.tree.command(name="test", description="Test des embeds")
async def test_embed(interaction: discord.Interaction, member: discord.Member):
    embed = discord.Embed(
        title="Test Title",
        description="Description de l'embed",
        color=discord.Color.blue()
    )
    embed.add_field(name="Python", value="Apprendre le python en s'amusant", inline=False)
    embed.add_field(name="Web", value="Apprendre le web en s'amusant", inline=False)
    embed.set_footer(text="Bas de message")
    embed.set_image(url="https://pixabay.com/fr/images/download/muhammadsaqii786-youtube-6621791_1920.jpg")

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="warnguy", description="Alerter une personne")
@discord.app_commands.default_permissions(ban_members=True)
async def warnguy(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.send_message("Alerte envoyée !", ephemeral=True)
    await member.send("Tu as reçu une alerte.")

@bot.tree.command(name="banguy", description="Bannir une personne")
@discord.app_commands.default_permissions(ban_members=True)
async def banguy(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.send_message("Ban effectué !", ephemeral=True)
    await member.send("Tu as été banni.")
    await member.ban(reason="Banni via commande staff")

@bot.tree.command(name="youtube", description="Affiche ma chaine youtube")
async def youtube(interaction: discord.Interaction):
    await interaction.response.send_message("Voici le lien de ma chaine Youtube: https://www.youtube.com/@GTGame24")

@bot.tree.command(name="isadraw", description="Affiche les Réseaux de la chaîne IsaDraw")
async def isadraw(interaction: discord.Interaction):
    embed = discord.Embed(
        title="IsaDraw",
        description="Découvrez les réseaux sociaux de IsaDraw n'hésitez pas à le suivre 😉!",
    )
    embed.add_field(name="Youtube", value="[Isa Draw](https://www.youtube.com/@Isa_Draw12)")
    embed.add_field(name="Instagram", value="[isadraw12](https://www.instagram.com/isadraw12)")
    embed.set_image(url="https://yt3.googleusercontent.com/9pdUfE3u2IG761i4xxNTWoncrOd2CtFQ6OIGxpDSGLID7sz-dKUVZdhYr_ftyGDvTo8Ke_yMhzA=s160-c-k-c0x00ffffff-no-rj")
    embed.set_footer(text="Chaîne de Dessin ✏️ !")

    await interaction.response.send_message(embed=embed)

@bot.event
async def on_member_join(member):
    channel = discord.utils.get(member.guild.text_channels, name='👋bienvenue👋')
    if channel:
        await channel.send(f'Bienvenue sur le serveur, {member.mention} ! 🎉 N\'hésite pas à lire le règlement.')

@bot.tree.command(name="hack_switch", description="Retrouvez l'endroit où se trouve les docs + Tuto sur hack_Switch")
async def hack_switch(interaction: discord.Interaction):
    channel = bot.get_channel(1497967551496458322)

    if channel is None:
        await interaction.response.send_message("Le salon spécifié est introuvable.", ephemeral=True)
        return

    await interaction.response.send_message(
        f"Salut {interaction.user.mention} ! Les fichiers/dossiers ainsi que les Tutos se trouvent dans le salon {channel.mention}. "
        "⚠️ Attention: Rappel: À suivre étape par étape sinon risque de Brick (Rendre la console inutilisable) ⚠️ À vos risques et périls ...",
        ephemeral=True
    )

@bot.tree.command(name="add_insulte", description="Ajouter un mot à la liste noire")
@discord.app_commands.default_permissions(administrator=True)
async def add_insulte(interaction: discord.Interaction, mot: str):
    if not DATABASE_URL:
        return await interaction.response.send_message("BDD non configurée.", ephemeral=True)
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO banned_words (word) VALUES (%s) ON CONFLICT DO NOTHING", (mot.lower(),))
        conn.commit()
        await interaction.response.send_message(f"✅ Le mot `{mot}` est maintenant interdit.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Erreur : {e}", ephemeral=True)
    finally:
        cur.close()
        conn.close()

@bot.tree.command(name="verification", description="Une commande pour obtenir le grade de membre Certifié")
async def verif(interaction: discord.Interaction, member: discord.Member):
    role_mention = f"<@&{VERIF_ROLE_ID}>"

    msg = await interaction.channel.send(
        f"{member.mention}, un modérateur va vérifier ta demande. Réagissez avec ✅ ou ❌."
    )
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")

    await interaction.response.send_message(
        f"Salut {interaction.user.mention} ! Pour devenir {role_mention} tu dois répondre à ce questionnaire. En cas d'acceptation, tu recevras un MP alors sois à l'affût 😉! "
        "⚠️ Attention: une fois certifié, la modération de ton compte sera réduite mais si tu enfreins une règle, ce sera tolérance zéro (Ban jusqu'à nouvel ordre!). ⚠️",
        ephemeral=True
    )

@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return

    mod_role = discord.utils.get(user.guild.roles, name="Modérateur")
    if mod_role not in user.roles:
        return

    if reaction.message.author != bot.user or not reaction.message.mentions:
        return

    member_to_notify = reaction.message.mentions[0]
    role_to_add = user.guild.get_role(VERIF_ROLE_ID)

    if str(reaction.emoji) == "✅":
        try:
            await member_to_notify.send("Bienvenue ! Votre demande de certification a été acceptée.")
        except discord.Forbidden:
            print(f"Impossible d'envoyer un MP à {member_to_notify}")

        if role_to_add:
            try:
                await member_to_notify.add_roles(role_to_add)
            except Exception as e:
                print(f"Erreur lors de l'ajout du rôle : {e}")

    elif str(reaction.emoji) == "❌":
        try:
            await member_to_notify.send("Désolé, votre demande de certification a été refusée.")
        except discord.Forbidden:
            print(f"Impossible d'envoyer un MP à {member_to_notify}")

@bot.tree.command(name="tempban", description="Bannir un membre temporairement")
@discord.app_commands.default_permissions(ban_members=True)
async def tempban(interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "Non spécifiée"):
    await interaction.response.send_message(f"🔨 {member.mention} a été banni pour {minutes} minutes. Raison : {reason}")
    
    try:
        await member.send(f"Tu as été banni de {interaction.guild.name} pendant {minutes} minutes pour : {reason}")
        await member.ban(reason=reason)
        
        await asyncio.sleep(minutes * 60)
        
        await interaction.guild.unban(member)
        print(f"{member.name} a été débanni après {minutes} minutes.")
    except Exception as e:
        print(f"Erreur lors du tempban : {e}")


@bot.tree.command(name="ban_history", description="Voir l'historique des bannissements")
@discord.app_commands.default_permissions(administrator=True)
async def history(interaction: discord.Interaction):
    if not DATABASE_URL:
        return await interaction.response.send_message("BDD non configurée.", ephemeral=True)
        
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT user_name, reason, proof, date FROM bans ORDER BY id DESC LIMIT 5")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        return await interaction.response.send_message("L'historique des bannissements est vide.", ephemeral=True)

    embed = discord.Embed(title="📜 Historique des Bans", color=discord.Color.red())
    for row in rows:
        embed.add_field(
            name=f"Utilisateur : {row[0]}",
            value=f"📅 Date: {row[3]}\n📝 Raison: {row[1]}\n📂 Preuve: {row[2]}",
            inline=False
        )
    await interaction.response.send_message(embed=embed)

# --- COMMANDE POUR RETIRER DES AVERTISSEMENTS ---
@bot.tree.command(name="unwarn", description="Retirer de 1 à 3 avertissements à un membre")
@discord.app_commands.default_permissions(ban_members=True)
@discord.app_commands.choices(nombre=[
    discord.app_commands.Choice(name="1 avertissement", value=1),
    discord.app_commands.Choice(name="2 avertissements", value=2),
    discord.app_commands.Choice(name="3 avertissements (Réinitialiser)", value=3)
])
async def unwarn(interaction: discord.Interaction, member: discord.Member, nombre: int):
    if not DATABASE_URL:
        return await interaction.response.send_message("❌ La base de données n'est pas configurée.", ephemeral=True)

    user_id = str(member.id)

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Récupération des warns actuels
        cur.execute("SELECT count FROM warnings WHERE user_id = %s", (user_id,))
        row = cur.fetchone()

        if not row or row[0] == 0:
            cur.close()
            conn.close()
            return await interaction.response.send_message(f"ℹ️ {member.mention} n'a aucun avertissement actif.", ephemeral=True)

        current_warns = row[0]
        new_warns = max(0, current_warns - nombre)

        if new_warns == 0:
            cur.execute("DELETE FROM warnings WHERE user_id = %s", (user_id,))
        else:
            cur.execute("UPDATE warnings SET count = %s, updated_at = CURRENT_TIMESTAMP WHERE user_id = %s", (new_warns, user_id))

        conn.commit()
        cur.close()
        conn.close()

        await interaction.response.send_message(
            f"✅ **{nombre}** avertissement(s) retiré(s) à {member.mention}.\n"
            f"📊 Nouveau total : **{new_warns}/3** avertissement(s)."
        )

    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur BDD : {e}", ephemeral=True)

@bot.tree.command(name="del_insulte", description="Retirer un mot de la liste noire")
@discord.app_commands.default_permissions(administrator=True)
async def del_insulte(interaction: discord.Interaction, mot: str):
    if not DATABASE_URL:
        return await interaction.response.send_message("❌ Base de données non configurée.", ephemeral=True)
    
    mot_lower = mot.lower().strip()

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Vérification si le mot existe dans la BDD
        cur.execute("SELECT word FROM banned_words WHERE word = %s", (mot_lower,))
        row = cur.fetchone()

        if not row:
            cur.close()
            conn.close()
            return await interaction.response.send_message(f"ℹ️ Le mot `{mot_lower}` n'était pas présent dans la liste noire de la BDD.", ephemeral=True)

        # Suppression du mot
        cur.execute("DELETE FROM banned_words WHERE word = %s", (mot_lower,))
        conn.commit()
        cur.close()
        conn.close()

        await interaction.response.send_message(f"✅ Le mot `{mot_lower}` a été retiré de la liste noire avec succès !", ephemeral=True)

    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur BDD : {e}", ephemeral=True)

@bot.tree.command(name="list_insultes", description="Afficher les mots interdits enregistrés en BDD")
@discord.app_commands.default_permissions(administrator=True)
async def list_insultes(interaction: discord.Interaction):
    if not DATABASE_URL:
        return await interaction.response.send_message("❌ Base de données non configurée.", ephemeral=True)

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT word FROM banned_words")
        rows = cur.fetchall()
        cur.close()
        conn.close()

        if not rows:
            return await interaction.response.send_message("ℹ️ Aucun mot personnalisé dans la base de données.", ephemeral=True)

        mots_list = ", ".join([f"`{row[0]}`" for row in rows])
        await interaction.response.send_message(f"📜 **Mots interdits en BDD :**\n{mots_list}", ephemeral=True)

    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur BDD : {e}", ephemeral=True)

# --- GESTION DES ERREURS DE COMMANDES ---
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.CheckFailure):
        await interaction.response.send_message("Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True)
    else:
        print(f"Erreur : {error}")

bot.run(os.getenv('DISCORD_TOKEN'))