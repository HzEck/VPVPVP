import discord
from discord import app_commands
from discord.ext import tasks
import aiohttp
import asyncio
import os
from datetime import datetime
from collections import defaultdict
from aiohttp import web

# ============= CONFIG =============
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN', 'YOUR_BOT_TOKEN')

# GTPS Cloud API - Sabit (değişmeyecek)
API_BASE_URL = 'https://api.gtps.cloud/g-api/1782'

# Ses kanalları
VP_CHANNEL_ID = int(os.getenv('VP_CHANNEL_ID', '0'))
GEMS_CHANNEL_ID = int(os.getenv('GEMS_CHANNEL_ID', '0'))

# Ödül ayarları
VP_AMOUNT = 10
VP_INTERVAL = 300  # 5 dakika
GEMS_MULTIPLIER = 1.05
GEMS_DURATION = 3600
GEMS_REFRESH = 60

# ============= BOT SETUP =============
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

class RewardsBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        
    async def setup_hook(self):
        await self.tree.sync()
        print("[BOT] Commands synced!")

bot = RewardsBot()

# Voice tracking
user_voice_data = defaultdict(lambda: {'vp_start': None, 'gems_start': None})

# ============= API =============
async def api_call(endpoint, data):
    async with aiohttp.ClientSession() as session:
        try:
            url = f"{API_BASE_URL}{endpoint}"
            print(f"[API] POST {url}")
            
            async with session.post(url, json=data, headers={'Content-Type': 'application/json'}, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    return {"success": False, "error": f"HTTP {response.status}"}
                
                result = await response.json()
                return result
                    
        except Exception as e:
            print(f"[API ERROR] {e}")
            return {"success": False, "error": str(e)}

async def verify_code(code, discord_id):
    return await api_call('/api/discord/verify', {'code': code, 'discordID': str(discord_id)})

async def get_linked(discord_id):
    return await api_call('/api/discord/get', {'discordID': str(discord_id)})

async def add_vp(discord_id, amount):
    return await api_call('/api/discord/reward/vp', {'discordID': str(discord_id), 'amount': amount})

async def add_gems_boost(discord_id, multiplier, duration):
    return await api_call('/api/discord/reward/gems', {'discordID': str(discord_id), 'multiplier': multiplier, 'duration': duration})

# ============= EVENTS =============
@bot.event
async def on_ready():
    print(f'[BOT] Logged in as {bot.user.name}')
    print(f'[BOT] API: {API_BASE_URL}')
    
    if not vp_task.is_running():
        vp_task.start()
    if not gems_task.is_running():
        gems_task.start()
    
    print('[BOT] Ready!')

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    
    discord_id = str(member.id)
    now = datetime.now()
    
    # VP kanalına girdi
    if after.channel and after.channel.id == VP_CHANNEL_ID:
        if user_voice_data[discord_id]['vp_start'] is None:
            user_voice_data[discord_id]['vp_start'] = now
            print(f"[VP] {member.name} joined")
    
    # VP kanalından çıktı
    elif before.channel and before.channel.id == VP_CHANNEL_ID:
        user_voice_data[discord_id]['vp_start'] = None
        print(f"[VP] {member.name} left")
    
    # Gems kanalına girdi
    if after.channel and after.channel.id == GEMS_CHANNEL_ID:
        if user_voice_data[discord_id]['gems_start'] is None:
            user_voice_data[discord_id]['gems_start'] = now
            print(f"[GEMS] {member.name} joined")
            
            result = await add_gems_boost(discord_id, GEMS_MULTIPLIER, GEMS_DURATION)
            if result.get('success'):
                try:
                    await member.send(f"💎 **{GEMS_MULTIPLIER}x Gems Boost Activated!**\nDuration: {GEMS_DURATION//60} minutes")
                except:
                    pass
    
    # Gems kanalından çıktı
    elif before.channel and before.channel.id == GEMS_CHANNEL_ID:
        user_voice_data[discord_id]['gems_start'] = None
        print(f"[GEMS] {member.name} left")

# ============= TASKS =============
@tasks.loop(seconds=VP_INTERVAL)
async def vp_task():
    try:
        channel = bot.get_channel(VP_CHANNEL_ID)
        if not channel:
            return
        
        now = datetime.now()
        
        for member in channel.members:
            if member.bot:
                continue
            
            discord_id = str(member.id)
            start_time = user_voice_data[discord_id]['vp_start']
            
            if start_time:
                elapsed = (now - start_time).total_seconds()
                
                if elapsed >= VP_INTERVAL:
                    result = await add_vp(discord_id, VP_AMOUNT)
                    
                    if result.get('success'):
                        print(f"[VP] +{VP_AMOUNT} to {member.name}")
                        try:
                            await member.send(f"💰 **+{VP_AMOUNT} VP!** Total: {result.get('totalVP',0)} VP")
                        except:
                            pass
                    
                    user_voice_data[discord_id]['vp_start'] = now
    
    except Exception as e:
        print(f"[VP ERROR] {e}")

@tasks.loop(seconds=GEMS_REFRESH)
async def gems_task():
    try:
        channel = bot.get_channel(GEMS_CHANNEL_ID)
        if not channel:
            return
        
        for member in channel.members:
            if member.bot:
                continue
            
            await add_gems_boost(str(member.id), GEMS_MULTIPLIER, GEMS_REFRESH)
    
    except Exception as e:
        print(f"[GEMS ERROR] {e}")

# ============= COMMANDS =============
@bot.tree.command(name='verify', description='Link your Growtopia account')
@app_commands.describe(code='6-digit code from /link in-game')
async def verify(interaction: discord.Interaction, code: str):
    await interaction.response.defer(ephemeral=True)
    
    code = code.upper().strip()
    result = await verify_code(code, str(interaction.user.id))
    
    if result.get('success'):
        embed = discord.Embed(title="✅ Linked!", color=discord.Color.green())
        embed.add_field(name="GrowID", value=f"`{result.get('growID')}`")
        embed.add_field(name="Rewards", value=f"VP Channel: <#{VP_CHANNEL_ID}>\nGems Channel: <#{GEMS_CHANNEL_ID}>", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send(f"❌ {result.get('error','Unknown error')}\n\nUse `/link` in-game first!", ephemeral=True)

@bot.tree.command(name='profile', description='Check your profile')
async def profile(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    result = await get_linked(str(interaction.user.id))
    
    if result.get('success'):
        embed = discord.Embed(title="🎮 Profile", color=discord.Color.blue())
        embed.add_field(name="GrowID", value=f"`{result.get('growID')}`")
        embed.add_field(name="Total VP", value=f"{result.get('totalVP',0):,}")
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send("❌ Not linked! Use `/link` in-game.", ephemeral=True)

@bot.tree.command(name='rewards', description='Reward info')
async def rewards(interaction: discord.Interaction):
    embed = discord.Embed(title="🎁 Rewards", color=discord.Color.gold())
    embed.add_field(name=f"💰 VP", value=f"<#{VP_CHANNEL_ID}>\n+{VP_AMOUNT} VP every {VP_INTERVAL//60} min", inline=False)
    embed.add_field(name=f"💎 Gems", value=f"<#{GEMS_CHANNEL_ID}>\n{GEMS_MULTIPLIER}x boost", inline=False)
    await interaction.response.send_message(embed=embed)

# ============= HEALTH CHECK =============
async def health_check(request):
    return web.Response(text="OK", status=200)

async def start_http_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    
    port = int(os.getenv('PORT', '10000'))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f'[HTTP] Port {port}')

# ============= MAIN =============
async def main():
    await start_http_server()
    await bot.start(DISCORD_TOKEN)

if __name__ == '__main__':
    print("[BOT] Starting...")
    print(f"[API] {API_BASE_URL}")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[BOT] Stopped")
