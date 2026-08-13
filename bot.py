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
OBSCENE_WORDS = []

# Texte officiel du Règlement
REGLEMENT_TEXT = """📜 **RÈGLEMENT DU SERVEUR**

1️⃣ **Traitez tout le monde avec respect.** Aucun harcèlement, sexisme, racisme ou discours de haine ne sera toléré.
2️⃣ **Pas de spam ni d'autopromotion** (invitations de serveurs, publicités, etc.) sans l'autorisation d'un modérateur du serveur, y compris via les MP envoyés aux autres membres.
3️⃣ **Pas de contenu obscène ou soumis à une limite d'âge**, qu'il s'agisse de texte, d'images ou de liens mettant en scène de la nudité, du sexe, de l'hyperviolence ou tout autre contenu explicite perturbant.
4️⃣ **Nous ne sommes en aucun cas responsable d'arnaque** Cependant nous punnisont tout de même les personnes arnaquant/scammant avec une sanction plus ou moins sévère en fonction des cas.
5️⃣ Si tu remarques quelque chose de **contraire aux règles** ou qui te rend mal à l'aise, informes-en les modérateurs. Nous voulons que ce serveur soit accueillant pour tout le monde !
6️⃣ **Pas de Mention/MP** (sauf si autorisé) pour les grades suivants: Modérateur, Fondateur et animations (En résumé tout les grades du staff)! Dans le cas d'une mention vous n'aurez droit qu'a 3 avertissement après le 3 ème un banissement temporaire voir à vie serait envisageable.

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
# --- VUE DE MODÉRATION (3 WARNS / AUTO-MOD) ---
class BanRequestView(View):
    def __init__(self, target_member: discord.Member, reason: str):
        super().__init__(timeout=None)
        self.target_member = target_member
        self.reason = reason

    @discord.ui.button(label="🔨 Bannir le membre", style=discord.ButtonStyle.danger, custom_id="ban_req_confirm")
    async def confirm_ban(self, interaction: discord.Interaction, button: Button):
        if not interaction.user.guild_permissions.ban_members:
            return await interaction.response.send_message("❌ Tu n'as pas la permission de bannir des membres.", ephemeral=True)
        
        try:
            # MP au membre avant le ban
            try:
                await self.target_member.send(
                    f"⚠️ Vous avez été banni du serveur **{interaction.guild.name}**.\n**Raison :** {self.reason}"
                )
            except Exception:
                pass

            await self.target_member.ban(reason=f"{self.reason} - Validé par {interaction.user.name}")
            
            # Enregistrement en BDD
            if DATABASE_URL:
                try:
                    conn = psycopg2.connect(DATABASE_URL)
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO bans (user_name, reason, proof) VALUES (%s, %s, %s)",
                        (str(self.target_member), self.reason, f"AutoMod (3 warns) - Approuvé par {interaction.user.name}")
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
                except Exception as e:
                    print(f"Erreur BDD enregistrement ban : {e}")

            for child in self.children:
                child.disabled = True

            embed = interaction.message.embeds[0]
            embed.color = discord.Color.dark_red()
            embed.title = "🔨 Bannissement Confirmé & Exécuté"
            embed.add_field(name="🛡️ Action réalisée par", value=interaction.user.mention, inline=False)

            await interaction.response.edit_message(embed=embed, view=self)
            await interaction.followup.send(f"✅ {self.target_member.mention} a été banni avec succès.")

        except Exception as e:
            await interaction.response.send_message(f"❌ Erreur lors du bannissement : {e}", ephemeral=True)

    @discord.ui.button(label="🔍 Recherche Avancée", style=discord.ButtonStyle.primary, custom_id="ban_req_search")
    async def advanced_search(self, interaction: discord.Interaction, button: Button):
        if not interaction.user.guild_permissions.ban_members:
            return await interaction.response.send_message("❌ Tu n'as pas la permission d'accéder aux infos de modération.", ephemeral=True)

        user_id = str(self.target_member.id)
        current_warns = 0
        total_bans = 0

        # Récupération des informations complémentaires en BDD
        if DATABASE_URL:
            try:
                conn = psycopg2.connect(DATABASE_URL)
                cur = conn.cursor()
                
                # Récupérer les warns actuels
                cur.execute("SELECT count FROM warnings WHERE user_id = %s", (user_id,))
                row_warn = cur.fetchone()
                if row_warn:
                    current_warns = row_warn[0]

                # Récupérer le nombre de bans historiques
                cur.execute("SELECT COUNT(*) FROM bans WHERE user_name LIKE %s", (f"%{self.target_member.name}%",))
                row_bans = cur.fetchone()
                if row_bans:
                    total_bans = row_bans[0]

                cur.close()
                conn.close()
            except Exception as e:
                print(f"Erreur BDD lors de la recherche avancée : {e}")

        # Formater les dates
        joined_at = self.target_member.joined_at.strftime("%d/%m/%Y à %H:%M") if self.target_member.joined_at else "Inconnue"
        created_at = self.target_member.created_at.strftime("%d/%m/%Y à %H:%M")
        
        # Liste des rôles (excluant @everyone)
        roles_list = [role.mention for role in self.target_member.roles if role.name != "@everyone"]
        roles_str = ", ".join(roles_list) if roles_list else "Aucun rôle particulier"

        # Construction de l'embed de recherche détaillée
        embed = discord.Embed(
            title=f"🔎 Rapport de Recherche Avancée : {self.target_member.display_name}",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.set_thumbnail(url=self.target_member.display_avatar.url)
        embed.add_field(name="🆔 Identifiant (ID)", value=f"`{self.target_member.id}`", inline=True)
        embed.add_field(name="👤 Nom d'utilisateur", value=f"`{self.target_member.name}`", inline=True)
        embed.add_field(name="🏷️ Surnom serveur", value=f"`{self.target_member.nick or 'Aucun'}`", inline=True)
        
        embed.add_field(name="📅 Création du compte", value=f"`{created_at}`", inline=True)
        embed.add_field(name="📥 Rejoint le serveur", value=f"`{joined_at}`", inline=True)
        embed.add_field(name="⚡ Statut de Bot", value="Oui" if self.target_member.bot else "Non", inline=True)

        embed.add_field(name="⚠️ Avertissements actifs (BDD)", value=f"**{current_warns}/3**", inline=True)
        embed.add_field(name="📜 Historique de bans (BDD)", value=f"**{total_bans}** fois", inline=True)
        embed.add_field(name="🛡️ Rôle le plus élevé", value=self.target_member.top_role.mention, inline=True)

        embed.add_field(name="🎭 Tous les rôles", value=roles_str, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

# --- ÉVÉNEMENT ON_READY ---
@bot.event
async def on_ready():
    print("Bot allumé !")
    check_youtube.start()
    clean_expired_warns.start()
    await update_reglement()
    
    try:
        guild = discord.Object(id=1497967134733766676)
        bot.tree.clear_commands(guild=guild)
        await bot.tree.sync(guild=guild)

        # 2. On synchronise uniquement en GLOBAL
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} commandes synchronisées globalement (doublons supprimés) !")
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
                    f"Salut Tout le monde <@&{ROLE_ID}> ! 👋 {content_type} de GTGaming est disponible ! **\n{latest_video.title}**\n{video_url}"
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
# Dictionnaire de secours en mémoire si la BDD flanche
memory_warnings = {}

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    content = message.content.lower()

    # 1. Récupération des mots interdits
    mots_interdits = [w.lower().strip() for w in OBSCENE_WORDS if w and w.strip()]
    if DATABASE_URL:
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cur = conn.cursor()
            cur.execute("SELECT word FROM banned_words")
            mots_bdd = [row[0].lower().strip() for row in cur.fetchall() if row[0]]
            mots_interdits.extend(mots_bdd)
            cur.close()
            conn.close()
        except Exception as e:
            print(f"⚠️ Erreur BDD lecture mots : {e}")

    # 2. Vérification si un mot interdit est présent
    mots_du_message = content.split()
    est_interdit = any(word in mots_du_message or word in content for word in mots_interdits if word)

    if est_interdit:
        try:
            await message.delete()
        except Exception as e:
            print(f"⚠️ Erreur suppression message : {e}")

        user_id = str(message.author.id)
        count = None

        # 3. Mettre à jour en BDD avec requête UPSERT
        if DATABASE_URL:
            try:
                conn = psycopg2.connect(DATABASE_URL)
                cur = conn.cursor()

                cur.execute('''
                    INSERT INTO warnings (user_id, count, updated_at)
                    VALUES (%s, 1, CURRENT_TIMESTAMP)
                    ON CONFLICT (user_id) 
                    DO UPDATE SET 
                        count = LEAST(warnings.count + 1, 3),
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING count;
                ''', (user_id,))

                row = cur.fetchone()
                if row:
                    count = row[0]

                conn.commit()
                cur.close()
                conn.close()
            except Exception as e:
                print(f"❌ ERREUR CRITIQUE BDD (Ecriture Warn) : {e}")

        # Secours en mémoire si la BDD est indisponible
        if count is None:
            memory_warnings[user_id] = min(memory_warnings.get(user_id, 0) + 1, 3)
            count = memory_warnings[user_id]

        # 4. Rapport détaillé dans Modo-Logs si 3/3 avertissements
# 4. Rapport détaillé dans Modo-Logs si 3/3 avertissements
        if count >= 3:
            mod_channel = bot.get_channel(MOD_LOG_CHANNEL_ID)
            if mod_channel:
                previous_bans_count = 0
                if DATABASE_URL:
                    try:
                        conn = psycopg2.connect(DATABASE_URL)
                        cur = conn.cursor()
                        cur.execute("SELECT COUNT(*) FROM bans WHERE user_name LIKE %s", (f"%{message.author.name}%",))
                        row_bans = cur.fetchone()
                        if row_bans:
                            previous_bans_count = row_bans[0]
                        cur.close()
                        conn.close()
                    except Exception as e:
                        print(f"Erreur calcul des anciens bans : {e}")

                joined_at = message.author.joined_at.strftime("%d/%m/%Y à %H:%M") if message.author.joined_at else "Inconnue"
                created_at = message.author.created_at.strftime("%d/%m/%Y à %H:%M")

                embed = discord.Embed(
                    title="🚨 Demande de Bannissement Requise (AutoMod)",
                    description=f"L'utilisateur {message.author.mention} a atteint **3/3 avertissements**.",
                    color=discord.Color.red(),
                    timestamp=datetime.datetime.now(datetime.timezone.utc)
                )
                embed.set_thumbnail(url=message.author.display_avatar.url)
                embed.add_field(name="👤 Membre", value=f"{message.author} (`{message.author.id}`)", inline=False)
                embed.add_field(name="📅 Arrivée sur le serveur", value=f"`{joined_at}`", inline=True)
                embed.add_field(name="🕒 Création du compte", value=f"`{created_at}`", inline=True)
                embed.add_field(name="🔨 Bans précédents en BDD", value=f"**{previous_bans_count}**", inline=True)
                embed.add_field(name="💬 Dernier message incriminé", value=f"```{message.content}```", inline=False)
                
                # Instruction explicite pour la réinitialisation/gestion des avertissements
                embed.add_field(
                    name="💡 Gestion des Avertissements",
                    value=f"Pour réduire ou réinitialiser les avertissements de ce membre, utilisez la commande :\n`/unwarn member:{message.author.mention} nombre:<1 à 3>`",
                    inline=False
                )

                view = BanRequestView(target_member=message.author, reason="3 avertissements (AutoMod)")
                await mod_channel.send(embed=embed, view=view)

            await message.channel.send(
                f"🚨 {message.author.mention}, vous avez atteint la limite de 3 avertissements. Une demande de bannissement a été transmise à la modération."
            )
        else:
            await message.channel.send(
                f"⚠️ {message.author.mention}, attention aux propos tenus ! ({count}/3)",
                delete_after=10
            )

    await bot.process_commands(message)

# --- COMMANDES SLASH (TREE) ---
@bot.tree.command(name="warnguy", description="Alerter une personne")
@discord.app_commands.default_permissions(ban_members=True)
async def warnguy(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.send_message("Alerte envoyée !", ephemeral=True)
    await member.send("Tu as reçu une alerte.")

@bot.tree.command(name="banguy", description="Bannir un membre et enregistrer le rapport dans les logs")
@discord.app_commands.default_permissions(ban_members=True)
async def banguy(interaction: discord.Interaction, member: discord.Member, raison: str):
    if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
        return await interaction.response.send_message("❌ Vous ne pouvez pas bannir ce membre car son rôle est supérieur ou égal au vôtre.", ephemeral=True)

    try:
        # Envoi d'un MP d'avertissement au membre avant le ban
        try:
            await member.send(f"⚠️ Vous avez été banni du serveur **{interaction.guild.name}** par {interaction.user.name}.\n**Raison :** {raison}")
        except Exception:
            pass

        # Exécution du bannissement
        await member.ban(reason=f"{raison} (Par {interaction.user.name})")

        # Enregistrement du ban dans la base de données
        if DATABASE_URL:
            try:
                conn = psycopg2.connect(DATABASE_URL)
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO bans (user_name, reason, proof) VALUES (%s, %s, %s)",
                    (str(member), raison, f"Commande /banguy par {interaction.user.name}")
                )
                conn.commit()
                cur.close()
                conn.close()
            except Exception as e:
                print(f"Erreur enregistrement ban BDD : {e}")

        # Rapport dans le salon Mod-Logs
        mod_channel = bot.get_channel(MOD_LOG_CHANNEL_ID)
        if mod_channel:
            joined_at = member.joined_at.strftime("%d/%m/%Y à %H:%M") if member.joined_at else "Inconnue"
            created_at = member.created_at.strftime("%d/%m/%Y à %H:%M")

            embed = discord.Embed(
                title="🔨 Bannissement Effectué",
                color=discord.Color.dark_red(),
                timestamp=datetime.datetime.now(datetime.timezone.utc)
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name="👤 Membre banni", value=f"{member} (`{member.id}`)", inline=False)
            embed.add_field(name="🛡️ Modérateur", value=interaction.user.mention, inline=True)
            embed.add_field(name="📅 Arrivée sur le serveur", value=f"`{joined_at}`", inline=True)
            embed.add_field(name="🕒 Création du compte", value=f"`{created_at}`", inline=True)
            embed.add_field(name="📝 Raison", value=f"```{raison}```", inline=False)

            await mod_channel.send(embed=embed)

        await interaction.response.send_message(f"✅ **{member.name}** a été banni avec succès.\n📝 **Raison :** {raison}", ephemeral=True)

    except Exception as e:
        await interaction.response.send_message(f"❌ Impossible de bannir le membre : {e}", ephemeral=True)

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
        f"Salut {interaction.user.mention} ! Pour devenir {role_mention} tu dois répondre à ce [questionnaire](https://forms.cloud.microsoft/r/JUYHq9z6Mc). En cas d'acceptation, tu recevras un MP alors sois à l'affût 😉!"
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