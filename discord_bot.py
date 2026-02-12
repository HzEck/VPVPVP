import discord
from discord import app_commands
from discord.ext import tasks
import aiohttp
import asyncio
import os
from datetime import datetime, timedelta
from collections import defaultdict
from aiohttp import web

# ============= KONFİGÜRASYON =============
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN', 'YOUR_DISCORD_BOT_TOKEN')

# API URL - Eğer Render'da host ediyorsan sunucu URL'ini gir
API_BASE_URL = os.getenv('API_BASE_URL', 'http://localhost:17091/casino')

# Ses kanalı ID'leri (bunları kendi sunucunuzdan alın)
VP_VOICE_CHANNEL_ID = int(os.getenv('VP_CHANNEL_ID', '0'))  # VP kazanma kanalı
GEMS_VOICE_CHANNEL_ID = int(os.getenv('GEMS_CHANNEL_ID', '0'))  # Gems boost kanalı

# Ödül ayarları
VP_REWARD_AMOUNT = 10  # Her 5 dakikada kazanılan VP
VP_REWARD_INTERVAL = 300  # 5 dakika (saniye)
GEMS_BOOST_MULTIPLIER = 1.05  # 1.05x gems boost
GEMS_BOOST_DURATION = 3600  # 1 saat (saniye)
GEMS_CHECK_INTERVAL = 60  # Her dakika kontrol

# ============= BOT SETUP =============
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

class MyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.synced = False

    async def setup_hook(self):
        await self.tree.sync()
        print("[BOT] Commands synced!")

bot = MyBot()

# Kullanıcı ses kanalı takibi
user_voice_time = defaultdict(lambda: {'vp_start': None, 'gems_start': None})

# ============= API FONKSİYONLARI =============
async def api_request(endpoint, data):
    """API'ye POST isteği gönder"""
    async with aiohttp.ClientSession() as session:
        try:
            url = f"{API_BASE_URL}{endpoint}"
            print(f"[API] Calling {url} with data: {data}")
            async with session.post(url, json=data, headers={'Content-Type': 'application/json'}) as response:
                result = await response.json()
                print(f"[API] Response: {result}")
                return result
        except Exception as e:
            print(f"[API ERROR] {endpoint}: {e}")
            return {"success": False, "error": str(e)}

async def verify_link_code(code, discord_id):
    """Link kodunu doğrula"""
    return await api_request('/api/discord/link/verify', {
        'code': code,
        'discordID': str(discord_id)
    })

async def get_linked_user(discord_id):
    """Discord ID'den bağlı kullanıcıyı getir"""
    return await api_request('/api/discord/user/get', {
        'discordID': str(discord_id)
    })

async def add_vp_reward(discord_id, amount):
    """VP ödülü ekle"""
    return await api_request('/api/discord/reward/vp', {
        'discordID': str(discord_id),
        'amount': amount
    })

async def add_gems_boost(discord_id, multiplier, duration):
    """Gems boost ekle"""
    return await api_request('/api/discord/reward/boost', {
        'discordID': str(discord_id),
        'multiplier': multiplier,
        'duration': duration
    })

# ============= BOT EVENTS =============
@bot.event
async def on_ready():
    print(f'[BOT] Logged in as {bot.user.name} ({bot.user.id})')
    print(f'[BOT] VP Channel: {VP_VOICE_CHANNEL_ID}')
    print(f'[BOT] Gems Channel: {GEMS_VOICE_CHANNEL_ID}')
    print(f'[BOT] API URL: {API_BASE_URL}')
    print('[BOT] Starting voice tracking tasks...')
    
    # Task'ları başlat
    if not check_vp_rewards.is_running():
        check_vp_rewards.start()
    if not check_gems_boost.is_running():
        check_gems_boost.start()
    
    print('[BOT] Ready!')

@bot.event
async def on_voice_state_update(member, before, after):
    """Ses kanalı değişikliklerini takip et"""
    if member.bot:
        return
    
    discord_id = str(member.id)
    now = datetime.now()
    
    # VP kanalına katıldı
    if after.channel and after.channel.id == VP_VOICE_CHANNEL_ID:
        if user_voice_time[discord_id]['vp_start'] is None:
            user_voice_time[discord_id]['vp_start'] = now
            print(f"[VP] {member.name} joined VP channel")
    
    # VP kanalından ayrıldı
    elif before.channel and before.channel.id == VP_VOICE_CHANNEL_ID:
        user_voice_time[discord_id]['vp_start'] = None
        print(f"[VP] {member.name} left VP channel")
    
    # Gems kanalına katıldı
    if after.channel and after.channel.id == GEMS_VOICE_CHANNEL_ID:
        if user_voice_time[discord_id]['gems_start'] is None:
            user_voice_time[discord_id]['gems_start'] = now
            print(f"[GEMS] {member.name} joined Gems channel")
            
            # Hemen boost ver
            result = await add_gems_boost(discord_id, GEMS_BOOST_MULTIPLIER, GEMS_BOOST_DURATION)
            if result.get('success'):
                try:
                    await member.send(f"💎 **Gems Boost Activated!**\n"
                                    f"Multiplier: {GEMS_BOOST_MULTIPLIER}x\n"
                                    f"Duration: {GEMS_BOOST_DURATION // 60} minutes")
                except:
                    pass
    
    # Gems kanalından ayrıldı
    elif before.channel and before.channel.id == GEMS_VOICE_CHANNEL_ID:
        user_voice_time[discord_id]['gems_start'] = None
        print(f"[GEMS] {member.name} left Gems channel")

# ============= TASKS =============
@tasks.loop(seconds=VP_REWARD_INTERVAL)
async def check_vp_rewards():
    """VP kanalındaki kullanıcılara ödül ver"""
    try:
        vp_channel = bot.get_channel(VP_VOICE_CHANNEL_ID)
        if not vp_channel:
            return
        
        now = datetime.now()
        
        for member in vp_channel.members:
            if member.bot:
                continue
            
            discord_id = str(member.id)
            start_time = user_voice_time[discord_id]['vp_start']
            
            if start_time:
                # 5 dakika geçti mi kontrol et
                elapsed = (now - start_time).total_seconds()
                
                if elapsed >= VP_REWARD_INTERVAL:
                    # Ödül ver
                    result = await add_vp_reward(discord_id, VP_REWARD_AMOUNT)
                    
                    if result.get('success'):
                        print(f"[VP REWARD] Gave {VP_REWARD_AMOUNT} VP to {member.name}")
                        
                        try:
                            await member.send(f"💰 **VP Earned!**\n"
                                            f"You earned {VP_REWARD_AMOUNT} VP for staying in the voice channel!\n"
                                            f"Total time: {int(elapsed / 60)} minutes")
                        except:
                            pass
                    else:
                        error = result.get('error', 'Unknown error')
                        if error == 'Not linked':
                            try:
                                await member.send("❌ **Account Not Linked**\n"
                                                f"Link your account in-game with `/link` command first!")
                            except:
                                pass
                    
                    # Timer'ı sıfırla
                    user_voice_time[discord_id]['vp_start'] = now
    
    except Exception as e:
        print(f"[VP REWARD ERROR] {e}")

@tasks.loop(seconds=GEMS_CHECK_INTERVAL)
async def check_gems_boost():
    """Gems kanalındaki kullanıcıların boost'unu yenile"""
    try:
        gems_channel = bot.get_channel(GEMS_VOICE_CHANNEL_ID)
        if not gems_channel:
            return
        
        for member in gems_channel.members:
            if member.bot:
                continue
            
            discord_id = str(member.id)
            
            # Boost'u yenile (süreyi uzat)
            await add_gems_boost(discord_id, GEMS_BOOST_MULTIPLIER, GEMS_CHECK_INTERVAL)
    
    except Exception as e:
        print(f"[GEMS BOOST ERROR] {e}")

# ============= SLASH COMMANDS =============
@bot.tree.command(name='link', description='Link your Growtopia account to Discord')
@app_commands.describe(code='The 6-digit code from in-game /link command')
async def link_account(interaction: discord.Interaction, code: str):
    """Discord hesabını Growtopia hesabına bağla"""
    await interaction.response.defer(ephemeral=True)
    
    code = code.upper().strip()
    discord_id = str(interaction.user.id)
    
    print(f"[LINK CMD] User {interaction.user.name} trying code {code}")
    
    # Doğrula
    result = await verify_link_code(code, discord_id)
    
    if result.get('success'):
        username = result.get('username', 'Unknown')
        await interaction.followup.send(
            f"✅ **Account Linked Successfully!**\n"
            f"Discord: {interaction.user.mention}\n"
            f"Growtopia: `{username}`\n\n"
            f"You can now earn rewards by joining voice channels!",
            ephemeral=True
        )
    else:
        error = result.get('error', 'Unknown error')
        await interaction.followup.send(
            f"❌ **Link Failed**\n"
            f"Error: {error}\n\n"
            f"Make sure you:\n"
            f"1. Used `/link` command in-game\n"
            f"2. Copied the code correctly\n"
            f"3. Used the code within 5 minutes",
            ephemeral=True
        )

@bot.tree.command(name='profile', description='Check your linked account information')
async def check_profile(interaction: discord.Interaction):
    """Bağlı hesap bilgilerini görüntüle"""
    await interaction.response.defer(ephemeral=True)
    
    discord_id = str(interaction.user.id)
    
    result = await get_linked_user(discord_id)
    
    if result.get('success'):
        username = result.get('username', 'Unknown')
        balance = result.get('balance', 0)
        
        embed = discord.Embed(title="🎮 Profile", color=discord.Color.green())
        embed.add_field(name="Discord", value=interaction.user.mention, inline=False)
        embed.add_field(name="Growtopia", value=f"`{username}`", inline=False)
        embed.add_field(name="Balance", value=f"{balance:,} WL", inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send(
            "❌ **Account Not Linked**\n"
            f"Use `/link <code>` to link your account!\n"
            f"Get code in-game with `/link` command.",
            ephemeral=True
        )

@bot.tree.command(name='rewards', description='View information about the reward system')
async def check_rewards(interaction: discord.Interaction):
    """Ödül sistemi hakkında bilgi"""
    embed = discord.Embed(title="🎁 Reward System", color=discord.Color.gold())
    
    embed.add_field(
        name="💰 VP Channel",
        value=f"Join <#{VP_VOICE_CHANNEL_ID}> to earn {VP_REWARD_AMOUNT} VP every {VP_REWARD_INTERVAL // 60} minutes!",
        inline=False
    )
    
    embed.add_field(
        name="💎 Gems Boost Channel",
        value=f"Join <#{GEMS_VOICE_CHANNEL_ID}> to get {GEMS_BOOST_MULTIPLIER}x gems boost!",
        inline=False
    )
    
    embed.add_field(
        name="📝 How to Start",
        value="1. Use `/link` in Growtopia\n"
              "2. Copy the 6-digit code\n"
              "3. Use `/link <code>` here in Discord\n"
              "4. Join voice channels to earn rewards!",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='help', description='Show all available commands')
async def help_command(interaction: discord.Interaction):
    """Yardım menüsü"""
    embed = discord.Embed(title="🤖 Bot Commands", color=discord.Color.blue())
    
    embed.add_field(name="/link <code>", value="Link your Growtopia account", inline=False)
    embed.add_field(name="/profile", value="Check your linked account", inline=False)
    embed.add_field(name="/rewards", value="View reward system info", inline=False)
    embed.add_field(name="/help", value="Show this message", inline=False)
    
    await interaction.response.send_message(embed=embed)

# ============= HEALTH CHECK HTTP SERVER =============
async def health_check(request):
    """Render için health check endpoint"""
    return web.Response(text="Discord bot is running!", status=200)

async def start_http_server():
    """Render için basit HTTP server (port binding için)"""
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    
    port = int(os.getenv('PORT', '10000'))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f'[HTTP] Health check server running on port {port}')

# ============= BOT BAŞLAT =============
async def main():
    """Bot ve HTTP server'ı birlikte çalıştır"""
    # HTTP server'ı başlat
    await start_http_server()
    
    # Bot'u başlat
    await bot.start(DISCORD_TOKEN)

if __name__ == '__main__':
    print("[BOT] Starting Discord bot...")
    print(f"[BOT] API URL: {API_BASE_URL}")
    
    if DISCORD_TOKEN == 'YOUR_DISCORD_BOT_TOKEN':
        print("[ERROR] Please set DISCORD_TOKEN environment variable!")
    else:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            print("[BOT] Shutting down...")
