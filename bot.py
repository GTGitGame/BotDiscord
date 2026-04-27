import discord
import os
from dotenv import load_dotenv
from keep_alive import keep_alive  # Import du fichier qu'on vient de créer
from discord.ext import commands
keep_alive()  # Lance le serveur web
load_dotenv()


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

@bot.event
async def on_message(message: discord.Message):
    # empecher auto déclenchement
    if message.author.bot:
        return
    
    if message.content.lower() == 'bonjour':
        channel = message.channel
        author = message.author
        await author.send("Comment tu vas ?")
    if message.content.lower() == "bienvenue":
        welcom_channel = bot.get_channel(1497967954950623272)
        await welcom_channel.send("Bienvenue sur le serveur discord !")

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
async def warnguy(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.send_message("Alerte envoyé !")
    await member.send("Tu as reçu une alerte")

@bot.tree.command(name="banguy", description="Alerter une personne")
async def banguy(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.send_message("Ban envoyé !")
    await member.ban(reason="Tu n'es pas abonné")
    await member.send("Tu as été Banni")

@bot.tree.command(name="youtube", description="Affiche ma chaine youtube")
async def youtube(interaction: discord.Interaction):
    await interaction.response.send_message("Voici le lien de ma chaine Youtube: https://www.youtube.com/@GTGame24")

@bot.event
async def on_member_join(member):
    # Chercher un canal nommé 'bienvenue' dans la guild où le membre a rejoint
    channel = discord.utils.get(member.guild.text_channels, name='bienvenue')
    if channel:
        # Envoyer un message de bienvenue personnalisé
        await channel.send(f'Bienvenue sur le serveur, {member.mention} ! 🎉')

@bot.tree.command(name="Hack_Switch", description="Retrouvez l'endroit où se trouve les docs + Tuto sur Hack_Switch")
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


@bot.tree.command(name="Vérification", description="Une commande pour obtenir le grade de membre Certifié")
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
    role_to_add = discord.utils.get(user.guild.roles, name="Membre Certifié")

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
        # Envoyer MP de refus
        try:
            await member_to_notify.send("Désolé, votre demande pour devenir Membre Certifié a été refusée.")
        except discord.Forbidden:
            print(f"Impossible d'envoyer un MP à {member_to_notify}")



bot.run(os.getenv('DISCORD_TOKEN'))