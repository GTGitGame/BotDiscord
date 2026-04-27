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
async def warnguy(interaction: discord.Interaction, member: discord.Member):
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
async def warnguy(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.send_message("Ban envoyé !")
    await member.ban(reason="Tu n'es pas abonné")
    await member.send("Tu as été Banni")

@bot.tree.command(name="youtube", description="Affiche ma chaine youtube")
async def youtube(interaction: discord.Interaction):
    await interaction.response.send_message("Voici le lien de ma chaine Youtube: https://www.youtube.com/@GTGame24")

bot.run(os.getenv('DISCORD_TOKEN'))