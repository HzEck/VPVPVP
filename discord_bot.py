import discord
from discord import app_commands
from discord.ext import tasks
import aiohttp
import asyncio
import os
from datetime import datetime
from collections import defaultdict
from aiohttp import web
import json

# ============= CONFIG =============
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN', 'YOUR_BOT_TOKEN')
API_BASE_URL = os.getenv('API_BASE_URL', 'https://api.gtps.cloud/g-api/18882')

# Voice channels
VP_CHANNEL_ID = int(os.getenv('VP_CHANNEL_ID', '1470057279511466045'))
GEMS_CHANNEL_ID = int(os.getenv('GEMS_CHANNEL_ID', '1470057299631411444'))

# Reward settings
VP_AMOUNT = 10
VP_INTERVAL = 300  # 5 minutes
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

# ============= GTPS CLOUD API =============
async def api_call(endpoint, data):
    """GTPS Cloud API call - simplified and fixed"""
    
    async with aiohttp.ClientSession() as session:
        try:
            url = f"{API_BASE_URL}{endpoint}"
            
            print(f"\n[API] >>> POST {url}")
            print(f"[API] >>> Data: {json.dumps(data, indent=2)}")
            
            # GTPS Cloud'a özel headers
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'User-Agent': 'DiscordVPBot/1.0'
            }
            
            async with session.post(
                url, 
                json=data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
                allow_redirects=False  # Cloudflare redirect'i önle
            ) as response:
                status = response.status
                text = await response.text()
                
                print(f"[API] <<< Status: {status}")
                print(f"[API] <<< Response: {text[:500]}")
                
                # Cloudflare check
                if 'cloudflare' in text.lower() or 'just a moment' in text.lower():
                    print("[API] ⚠️ Cloudflare protection detected")
                    return {"success": False, "error": "Cloudflare protection"}
                
                # Empty response
                if not text or text.strip() == "":
                    print("[API] ⚠️ Empty response")
                    return {"success": False, "error": "Server returned empty response"}
                
                # Parse JSON
                try:
                    result = json.loads(text)
                    print(f"[API] ✅ Success!")
                    return result
                except json.JSONDecodeError as e:
                    print(f"[API] ❌ JSON parse error: {e}")
                    print(f"[API] Raw text: {text}")
                    
                    # Lua might return plain text sometimes
                    if text.startswith('{') and text.endswith('}'):
                        # Try manual parse
                        return {"success": False, "error": "Invalid JSON", "raw": text}
                    
                    return {"success": False, "error": "Invalid response format"}
                    
        except asyncio.TimeoutError:
            print("[API] ❌ Timeout")
            return {"success": False, "error": "Request timeout"}
        except Exception as e:
            print(f"[API] ❌ Error: {e}")
            return {"success": False, "error": str(e)}

async def link_account(username, code, discord_id):
    """Link account - FIXED endpoint"""
    return await api_call('/api/discord/link', {
        'username': username,
        'code': code,
        'discordID': str(discord_id)
    })

async def get_profile(discord_id):
    """Get profile"""
    return await api_call('/api/discord/get', {
        'discordID': str(discord_id)
    })

async def add_vp(discord_id, amount):
    """Add VP"""
    return await api_call('/api/discord/reward/vp', {
        'discordID': str(discord_id),
        'amount': amount
    })

async def add_gems_boost(discord_id, multiplier, duration):
    """Add gems boost"""
    return await api_call('/api/discord/reward/gems', {
        'discordID': str(discord_id),
        'multiplier': multiplier,
        'duration': duration
    })

# ============= EVENTS =============
@bot.event
async def on_ready():
    print(f'\n[BOT] ✅ Logged in as {bot.user.name}')
    print(f'[BOT] 🔗 API: {API_BASE_URL}')
    print(f'[BOT] 💰 VP Channel: {VP_CHANNEL_ID}')
    print(f'[BOT] 💎 Gems Channel: {GEMS_CHANNEL_ID}')
    
    # Tasks başlat
    if not vp_task.is_running():
        vp_task.start()
    if not gems_task.is_running():
        gems_task.start()
    
    print('[BOT] 🚀 Ready!\n')

@bot.event
async def on_voice_state_update(member, before, after):
    """Ses kanalı değişiklikleri"""
    if member.bot:
        return
    
    discord_id = str(member.id)
    now = datetime.now()
    
    # VP kanalı
    if after.channel and after.channel.id == VP_CHANNEL_ID:
        if user_voice_data[discord_id]['vp_start'] is None:
            user_voice_data[discord_id]['vp_start'] = now
            print(f"[VP] {member.name} joined VP channel")
    elif before.channel and before.channel.id == VP_CHANNEL_ID:
        user_voice_data[discord_id]['vp_start'] = None
        print(f"[VP] {member.name} left VP channel")
    
    # Gems kanalı
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
                        f"• Duration: **{GEMS_DURATION // 60} minutes**"
                    )
                except:
                    pass
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
                    result = await add_vp(discord_id, VP_AMOUNT)
                    
                    if result.get('success'):
                        print(f"[VP] ✅ Gave {VP_AMOUNT} VP to {member.name}")
                        
                        try:
                            await member.send(
                                f"💰 **VP Earned!**\n"
                                f"• Amount: **+{VP_AMOUNT} VP**\n"
                                f"• Total: **{result.get('totalVP', 0)}**\n"
                                f"• Time: **{int(elapsed / 60)} minutes**"
                            )
                        except:
                            pass
                    else:
                        if result.get('error') == 'Not linked':
                            try:
                                await member.send(
                                    "❌ **Account Not Linked**\n"
                                    "Type `/linkvp` in Growtopia to link your account!"
                                )
                            except:
                                pass
                    
                    user_voice_data[discord_id]['vp_start'] = now
    
    except Exception as e:
        print(f"[VP ERROR] {e}")

@tasks.loop(seconds=GEMS_REFRESH)
async def gems_task():
    """Gems boost refresh"""
    try:
        channel = bot.get_channel(GEMS_CHANNEL_ID)
        if not channel:
            return
        
        for member in channel.members:
            if member.bot:
                continue
            
            discord_id = str(member.id)
            await add_gems_boost(discord_id, GEMS_MULTIPLIER, GEMS_REFRESH)
    
    except Exception as e:
        print(f"[GEMS ERROR] {e}")

# ============= COMMANDS =============
@bot.tree.command(name='linkvp', description='Link your Growtopia account')
@app_commands.describe(
    username='Your GrowID (Growtopia username)',
    code='6-digit code from /linkvp command in-game'
)
async def linkvp(interaction: discord.Interaction, username: str, code: str):
    """Link account - FIXED"""
    await interaction.response.defer(ephemeral=True)
    
    username = username.strip()
    code = code.upper().strip()
    discord_id = str(interaction.user.id)
    
    print(f"\n[LINK CMD] User: {interaction.user.name}")
    print(f"[LINK CMD] GrowID: {username}")
    print(f"[LINK CMD] Code: {code}")
    print(f"[LINK CMD] Discord ID: {discord_id}")
    
    result = await link_account(username, code, discord_id)
    
    print(f"[LINK CMD] Result: {result}")
    
    if result.get('success'):
        embed = discord.Embed(
            title="✅ Account Linked!",
            description=f"Successfully linked your accounts!",
            color=discord.Color.green()
        )
        embed.add_field(name="Discord", value=interaction.user.mention, inline=False)
        embed.add_field(name="GrowID", value=f"`{username}`", inline=False)
        embed.add_field(
            name="🎁 Rewards Active",
            value=f"• <#{VP_CHANNEL_ID}> → **{VP_AMOUNT} VP** every {VP_INTERVAL // 60} min\n"
                  f"• <#{GEMS_CHANNEL_ID}> → **{GEMS_MULTIPLIER}x gems boost**",
            inline=False
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        error = result.get('error', 'Unknown error')
        
        embed = discord.Embed(
            title="❌ Link Failed",
            description=f"Error: `{error}`",
            color=discord.Color.red()
        )
        embed.add_field(
            name="📝 Steps to Link",
            value="1. Type `/linkvp` in-game\n"
                  "2. Copy your **GrowID** (username)\n"
                  "3. Copy the **6-digit code**\n"
                  "4. Enter both here within 5 minutes",
            inline=False
        )
        embed.add_field(
            name="⚠️ Common Issues",
            value="• Code expired? Get a new one with `/linkvp`\n"
                  "• Check your GrowID spelling\n"
                  "• Make sure you're using the latest code",
            inline=False
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name='profile', description='Check your linked account')
async def profile(interaction: discord.Interaction):
    """Profil göster"""
    await interaction.response.defer(ephemeral=True)
    
    discord_id = str(interaction.user.id)
    
    result = await get_profile(discord_id)
    
    if result.get('success'):
        growid = result.get('growID', 'Unknown')
        total_vp = result.get('totalVP', 0)
        
        embed = discord.Embed(
            title="🎮 Your Profile",
            color=discord.Color.blue()
        )
        embed.add_field(name="Discord", value=interaction.user.mention, inline=False)
        embed.add_field(name="GrowID", value=f"`{growid}`", inline=False)
        embed.add_field(name="Total VP", value=f"**{total_vp:,}**", inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send(
            "❌ **Not Linked**\n"
            "Use `/linkvp <username> <code>` to link your account!\n"
            "Get code with `/linkvp` command in Growtopia.",
            ephemeral=True
        )

@bot.tree.command(name='rewards', description='View reward system')
async def rewards(interaction: discord.Interaction):
    """Ödül bilgisi"""
    embed = discord.Embed(
        title="🎁 Voice Rewards System",
        description="Earn rewards by staying in voice channels!",
        color=discord.Color.gold()
    )
    
    embed.add_field(
        name="💰 VP Channel",
        value=f"<#{VP_CHANNEL_ID}>\n"
              f"• Earn **{VP_AMOUNT} VP** every **{VP_INTERVAL // 60} minutes**",
        inline=False
    )
    
    embed.add_field(
        name="💎 Gems Boost Channel",
        value=f"<#{GEMS_CHANNEL_ID}>\n"
              f"• Get **{GEMS_MULTIPLIER}x gems** multiplier\n"
              f"• Lasts **{GEMS_DURATION // 60} minutes**",
        inline=False
    )
    
    embed.add_field(
        name="📝 How to Start",
        value="1. Type `/linkvp` in Growtopia\n"
              "2. Copy your GrowID and code\n"
              "3. Use `/linkvp <username> <code>` here\n"
              "4. Join voice channels!",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='help', description='Show help')
async def help_cmd(interaction: discord.Interaction):
    """Yardım"""
    embed = discord.Embed(
        title="🤖 Bot Commands",
        color=discord.Color.purple()
    )
    
    embed.add_field(
        name="/linkvp <username> <code>",
        value="Link your Growtopia account",
        inline=False
    )
    embed.add_field(name="/profile", value="View your stats", inline=False)
    embed.add_field(name="/rewards", value="View reward info", inline=False)
    embed.add_field(name="/help", value="Show this message", inline=False)
    
    await interaction.response.send_message(embed=embed)

# ============= HEALTH CHECK =============
async def health_check(request):
    return web.Response(text="VP Bot is running!", status=200)

async def start_http_server():
    """HTTP server for Render"""
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    
    port = int(os.getenv('PORT', '10000'))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f'[HTTP] Health check on port {port}')

# ============= MAIN =============
async def main():
    await start_http_server()
    await bot.start(DISCORD_TOKEN)

if __name__ == '__main__':
    print("\n" + "="*50)
    print("    DISCORD VP REWARDS BOT")
    print("="*50)
    print(f"API: {API_BASE_URL}")
    print(f"VP Channel: {VP_CHANNEL_ID}")
    print(f"Gems Channel: {GEMS_CHANNEL_ID}")
    print("="*50 + "\n")
    
    if DISCORD_TOKEN == 'YOUR_BOT_TOKEN':
        print("[ERROR] Set DISCORD_TOKEN!")
    else:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            print("\n[BOT] Shutting down...")
