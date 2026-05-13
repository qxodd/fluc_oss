import discord
from discord.ext import commands

bot = commands.Bot(command_prefix=[''], self_bot=True)

@bot.event
async def on_ready():
    with open('member.txt', 'w') as file:
        guild = bot.get_guild(0)
        if not guild:
            print('Guild not found')
            return
        for member in guild.members:
            file.write(f'{member.id}\n')


bot.run('')