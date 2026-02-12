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
API_BASE_URL = os.getenv('API_BASE_URL', 'http://localhost:17091')  # Growtopia sunucunun URL'si

# Ses kanalları
VP_CHANNEL_ID = int(os.getenv('VP_CHANNEL_ID', '0'))
GEMS_CHANNEL_ID = int(os.getenv('GEMS_CHANNEL_ID', '0'))

# Ödül ayarları
VP_AMOUNT = 10  # Her 5 dakikada
VP_INTERVAL = 300  # 5 dakika
GEMS_MULTIPLIER = 1.05  # 1.05x
GEMS_DURATION = 3600  # 1 saat
GEMS_REFRESH = 60  # Her dakika refresh

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
    """API çağrısı yap"""
    async with aiohttp.ClientSession() as session:
        try:
            url = f"{API_BASE_URL}{endpoint}"
            print(f"[API] POST {url}")
            print(f"[API] Data: {data}")
            
            async with session.post(url, json=data, headers={'Content-Type': 'application/json'}) as response:
                result = await response.json()
                print(f"[API] Response: {result}")
                return result
        except Exception as e:
            print(f"[API ERROR] {e}")
            return {"success": False, "error": str(e)}

async def verify_code(code, discord_id):
    """Kodu doğrula"""
    return await api_call('/api/discord/verify', {
        'code': code,
        'discordID': str(discord_id)
    })

async def get_linked(discord_id):
    """Bağlı hesabı getir"""
    return await api_call('/api/discord/get', {
        'discordID': str(discord_id)
    })

async def add_vp(discord_id, amount):
    """VP ekle"""
    return await api_call('/api/discord/reward/vp', {
        'discordID': str(discord_id),
        'amount': amount
    })

async def add_gems_boost(discord_id, multiplier, duration):
    """Gems boost ekle"""
    return await api_call('/api/discord/reward/gems', {
        'discordID': str(discord_id),
        'multiplier': multiplier,
        'duration': duration
    })

# ============= EVENTS =============
@bot.event
async def on_ready():
    print(f'[BOT] Logged in as {bot.user.name}')
    print(f'[BOT] VP Channel: {VP_CHANNEL_ID}')
    print(f'[BOT] Gems Channel: {GEMS_CHANNEL_ID}')
    print(f'[BOT] API: {API_BASE_URL}')
    
    # Tasks başlat
    if not vp_task.is_running():
        vp_task.start()
    if not gems_task.is_running():
        gems_task.start()
    
    print('[BOT] Ready!')

@bot.event
async def on_voice_state_update(member, before, after):
    """Ses kanalı değişiklikleri"""
    if member.bot:
        return
    
    discord_id = str(member.id)
    now = datetime.now()
    
    # VP kanalına girdi
    if after.channel and after.channel.id == VP_CHANNEL_ID:
        if user_voice_data[discord_id]['vp_start'] is None:
            user_voice_data[discord_id]['vp_start'] = now
            print(f"[VP] {member.name} joined VP channel")
    
    # VP kanalından çıktı
    elif before.channel and before.channel.id == VP_CHANNEL_ID:
        user_voice_data[discord_id]['vp_start'] = None
        print(f"[VP] {member.name} left VP channel")
    
    # Gems kanalına girdi
    if after.channel and after.channel.id == GEMS_CHANNEL_ID:
        if user_voice_data[discord_id]['gems_start'] is None:
            user_voice_data[discord_id]['gems_start'] = now
            print(f"[GEMS] {member.name} joined Gems channel")
            
            # Boost ver
            result = await add_gems_boost(discord_id, GEMS_MULTIPLIER, GEMS_DURATION)
            if result.get('success'):
                try:
                    await member.send(
                        f"💎 **Gems Boost Activated!**\n"
                        f"• Multiplier: **{GEMS_MULTIPLIER}x**\n"
                        f"• Duration: **{GEMS_DURATION // 60} minutes**\n"
                        f"• GrowID: `{result.get('growID')}`"
                    )
                except:
                    pass
    
    # Gems kanalından çıktı
    elif before.channel and before.channel.id == GEMS_CHANNEL_ID:
        user_voice_data[discord_id]['gems_start'] = None
        print(f"[GEMS] {member.name} left Gems channel")

# ============= TASKS =============
@tasks.loop(seconds=VP_INTERVAL)
async def vp_task():
    """VP ödülü ver"""
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
                    # VP ver
                    result = await add_vp(discord_id, VP_AMOUNT)
                    
                    if result.get('success'):
                        print(f"[VP] Gave {VP_AMOUNT} VP to {member.name}")
                        
                        try:
                            await member.send(
                                f"💰 **VP Earned!**\n"
                                f"• Amount: **+{VP_AMOUNT} VP**\n"
                                f"• Total VP: **{result.get('totalVP')}**\n"
                                f"• Time: **{int(elapsed / 60)} minutes**"
                            )
                        except:
                            pass
                    else:
                        if result.get('error') == 'Not linked':
                            try:
                                await member.send(
                                    "❌ **Account Not Linked**\n"
                                    "Use `/link` in Growtopia to get your code!\n"
                                    "Then use `/verify <code>` here in Discord."
                                )
                            except:
                                pass
                    
                    # Timer reset
                    user_voice_data[discord_id]['vp_start'] = now
    
    except Exception as e:
        print(f"[VP ERROR] {e}")

@tasks.loop(seconds=GEMS_REFRESH)
async def gems_task():
    """Gems boost'u refresh et"""
    try:
        channel = bot.get_channel(GEMS_CHANNEL_ID)
        if not channel:
            return
        
        for member in channel.members:
            if member.bot:
                continue
            
            discord_id = str(member.id)
            
            # Boost'u uzat
            await add_gems_boost(discord_id, GEMS_MULTIPLIER, GEMS_REFRESH)
    
    except Exception as e:
        print(f"[GEMS ERROR] {e}")

# ============= COMMANDS =============
@bot.tree.command(name='verify', description='Verify your link code from Growtopia')
@app_commands.describe(code='6-digit code from /link command in-game')
async def verify(interaction: discord.Interaction, code: str):
    """Kodu doğrula"""
    await interaction.response.defer(ephemeral=True)
    
    code = code.upper().strip()
    discord_id = str(interaction.user.id)
    
    print(f"[VERIFY] User {interaction.user.name} code {code}")
    
    result = await verify_code(code, discord_id)
    
    if result.get('success'):
        growid = result.get('growID')
        
        embed = discord.Embed(
            title="✅ Account Linked!",
            description=f"Successfully linked your accounts!",
            color=discord.Color.green()
        )
        embed.add_field(name="Discord", value=interaction.user.mention, inline=False)
        embed.add_field(name="GrowID", value=f"`{growid}`", inline=False)
        embed.add_field(
            name="🎁 Rewards",
            value=f"• Join <#{VP_CHANNEL_ID}> → Earn **{VP_AMOUNT} VP** every {VP_INTERVAL // 60} minutes\n"
                  f"• Join <#{GEMS_CHANNEL_ID}> → Get **{GEMS_MULTIPLIER}x gems boost**",
            inline=False
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        error = result.get('error', 'Unknown error')
        await interaction.followup.send(
            f"❌ **Verification Failed**\n"
            f"Error: `{error}`\n\n"
            f"**Steps:**\n"
            f"1. Use `/link` in Growtopia\n"
            f"2. Copy the 6-digit code\n"
            f"3. Use `/verify <code>` within 5 minutes",
            ephemeral=True
        )

@bot.tree.command(name='profile', description='Check your linked account')
async def profile(interaction: discord.Interaction):
    """Profil göster"""
    await interaction.response.defer(ephemeral=True)
    
    discord_id = str(interaction.user.id)
    
    result = await get_linked(discord_id)
    
    if result.get('success'):
        growid = result.get('growID')
        total_vp = result.get('totalVP', 0)
        
        embed = discord.Embed(
            title="🎮 Your Profile",
            color=discord.Color.blue()
        )
        embed.add_field(name="Discord", value=interaction.user.mention, inline=False)
        embed.add_field(name="GrowID", value=f"`{growid}`", inline=False)
        embed.add_field(name="Total VP Earned", value=f"**{total_vp:,}** VP", inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send(
            "❌ **Not Linked**\n"
            "Use `/link` in Growtopia to get your code!\n"
            "Then use `/verify <code>` here.",
            ephemeral=True
        )

@bot.tree.command(name='rewards', description='View reward system information')
async def rewards(interaction: discord.Interaction):
    """Ödül bilgisi"""
    embed = discord.Embed(
        title="🎁 Discord Voice Rewards",
        description="Earn rewards by joining voice channels!",
        color=discord.Color.gold()
    )
    
    embed.add_field(
        name="💰 VP Channel",
        value=f"<#{VP_CHANNEL_ID}>\n"
              f"• Earn **{VP_AMOUNT} VP** every **{VP_INTERVAL // 60} minutes**\n"
              f"• Stay in channel to earn!",
        inline=False
    )
    
    embed.add_field(
        name="💎 Gems Boost Channel",
        value=f"<#{GEMS_CHANNEL_ID}>\n"
              f"• Get **{GEMS_MULTIPLIER}x gems** multiplier\n"
              f"• Boost lasts **{GEMS_DURATION // 60} minutes**\n"
              f"• Automatically refreshed while in channel",
        inline=False
    )
    
    embed.add_field(
        name="📝 How to Start",
        value="1. Use `/link` in Growtopia\n"
              "2. Copy the 6-digit code\n"
              "3. Use `/verify <code>` in Discord\n"
              "4. Join voice channels to earn!",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='help', description='Show all commands')
async def help_cmd(interaction: discord.Interaction):
    """Yardım"""
    embed = discord.Embed(
        title="🤖 Commands",
        color=discord.Color.purple()
    )
    
    embed.add_field(name="/verify <code>", value="Link your Growtopia account", inline=False)
    embed.add_field(name="/profile", value="View your profile", inline=False)
    embed.add_field(name="/rewards", value="View reward system info", inline=False)
    embed.add_field(name="/help", value="Show this message", inline=False)
    
    await interaction.response.send_message(embed=embed)

# ============= HEALTH CHECK =============
async def health_check(request):
    return web.Response(text="Bot is running!", status=200)

async def start_http_server():
    """HTTP server (Render için)"""
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    
    port = int(os.getenv('PORT', '10000'))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f'[HTTP] Server on port {port}')

# ============= MAIN =============
async def main():
    await start_http_server()
    await bot.start(DISCORD_TOKEN)

if __name__ == '__main__':
    print("[DISCORD REWARDS BOT] Starting...")
    print(f"[CONFIG] API: {API_BASE_URL}")
    print(f"[CONFIG] VP Channel: {VP_CHANNEL_ID}")
    print(f"[CONFIG] Gems Channel: {GEMS_CHANNEL_ID}")
    
    if DISCORD_TOKEN == 'YOUR_BOT_TOKEN':
        print("[ERROR] Set DISCORD_TOKEN environment variable!")
    else:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            print("[BOT] Shutting down...")
