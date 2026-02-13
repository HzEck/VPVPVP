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

# GTPS Cloud API - Simplified system
API_BASE_URL = os.getenv('API_BASE_URL', 'https://api.gtps.cloud/g-api/1782')

# Voice channels
VP_CHANNEL_ID = int(os.getenv('VP_CHANNEL_ID', '1470057279511466045'))
GEMS_CHANNEL_ID = int(os.getenv('GEMS_CHANNEL_ID', '1470057299631411444'))

# Reward settings
VP_AMOUNT = 10
VP_INTERVAL = 300  # 5 minutes
GEMS_MULTIPLIER = 1.05
GEMS_DURATION = 3600  # 1 hour
GEMS_REFRESH = 60  # 1 minute

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

# ============= API HELPERS =============
async def api_call(endpoint, data):
    """Make API call to Lua server"""
    async with aiohttp.ClientSession() as session:
        try:
            url = f"{API_BASE_URL}{endpoint}"
            print(f"[API] POST {url} | Data: {data}")
            
            async with session.post(
                url, 
                json=data, 
                headers={'Content-Type': 'application/json'}, 
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                
                text = await response.text()
                print(f"[API] Response ({response.status}): {text[:200]}")
                
                if response.status != 200:
                    return {"success": False, "error": f"HTTP {response.status}"}
                
                result = await response.json()
                return result
                    
        except Exception as e:
            print(f"[API ERROR] {e}")
            return {"success": False, "error": str(e)}

async def get_profile(discord_id):
    """Get user profile from Lua"""
    return await api_call('/api/discord/get', {'discordID': str(discord_id)})

async def add_vp(discord_id, amount):
    """Add VP to user"""
    return await api_call('/api/discord/reward/vp', {
        'discordID': str(discord_id), 
        'amount': amount
    })

async def add_gems_boost(discord_id, multiplier, duration):
    """Add gems boost to user"""
    return await api_call('/api/discord/reward/gems', {
        'discordID': str(discord_id), 
        'multiplier': multiplier, 
        'duration': duration
    })

# ============= EVENTS =============
@bot.event
async def on_ready():
    print(f'[BOT] Logged in as {bot.user.name} ({bot.user.id})')
    print(f'[CONFIG] API: {API_BASE_URL}')
    print(f'[CONFIG] VP Channel: {VP_CHANNEL_ID}')
    print(f'[CONFIG] Gems Channel: {GEMS_CHANNEL_ID}')
    print(f'[CONFIG] VP: +{VP_AMOUNT} every {VP_INTERVAL//60} min')
    print(f'[CONFIG] Gems: {GEMS_MULTIPLIER}x boost')
    
    if not vp_task.is_running():
        vp_task.start()
        print('[TASK] VP reward task started')
    
    if not gems_task.is_running():
        gems_task.start()
        print('[TASK] Gems boost task started')
    
    print('[BOT] ✅ Ready!')

@bot.event
async def on_voice_state_update(member, before, after):
    """Handle voice channel join/leave"""
    if member.bot:
        return
    
    discord_id = str(member.id)
    now = datetime.now()
    
    # ===== VP CHANNEL =====
    # Joined VP channel
    if after.channel and after.channel.id == VP_CHANNEL_ID:
        if user_voice_data[discord_id]['vp_start'] is None:
            user_voice_data[discord_id]['vp_start'] = now
            print(f"[VP] ✅ {member.name} joined VP channel")
    
    # Left VP channel
    elif before.channel and before.channel.id == VP_CHANNEL_ID:
        if user_voice_data[discord_id]['vp_start'] is not None:
            duration = (now - user_voice_data[discord_id]['vp_start']).total_seconds()
            print(f"[VP] ❌ {member.name} left VP channel (was there {duration//60:.0f} min)")
            user_voice_data[discord_id]['vp_start'] = None
    
    # ===== GEMS CHANNEL =====
    # Joined Gems channel
    if after.channel and after.channel.id == GEMS_CHANNEL_ID:
        if user_voice_data[discord_id]['gems_start'] is None:
            user_voice_data[discord_id]['gems_start'] = now
            print(f"[GEMS] ✅ {member.name} joined Gems channel")
            
            # Activate boost immediately
            result = await add_gems_boost(discord_id, GEMS_MULTIPLIER, GEMS_DURATION)
            
            if result.get('success'):
                print(f"[GEMS] ✅ Boost activated for {member.name}")
                try:
                    await member.send(
                        f"💎 **Gems Boost Activated!**\n"
                        f"Multiplier: **{GEMS_MULTIPLIER}x**\n"
                        f"Duration: **{GEMS_DURATION//60} minutes**\n\n"
                        f"Break blocks in-game to earn bonus gems!"
                    )
                except:
                    print(f"[GEMS] ⚠️ Couldn't DM {member.name}")
            else:
                print(f"[GEMS] ❌ Failed to activate boost: {result.get('error')}")
    
    # Left Gems channel
    elif before.channel and before.channel.id == GEMS_CHANNEL_ID:
        if user_voice_data[discord_id]['gems_start'] is not None:
            duration = (now - user_voice_data[discord_id]['gems_start']).total_seconds()
            print(f"[GEMS] ❌ {member.name} left Gems channel (was there {duration//60:.0f} min)")
            user_voice_data[discord_id]['gems_start'] = None

# ============= TASKS =============
@tasks.loop(seconds=VP_INTERVAL)
async def vp_task():
    """Give VP to users in VP channel every interval"""
    try:
        channel = bot.get_channel(VP_CHANNEL_ID)
        if not channel:
            print(f"[VP TASK] ⚠️ Channel {VP_CHANNEL_ID} not found")
            return
        
        if len(channel.members) == 0:
            return  # No one in channel
        
        now = datetime.now()
        rewarded = 0
        
        for member in channel.members:
            if member.bot:
                continue
            
            discord_id = str(member.id)
            start_time = user_voice_data[discord_id]['vp_start']
            
            if start_time:
                elapsed = (now - start_time).total_seconds()
                
                # Give reward if user has been in channel for full interval
                if elapsed >= VP_INTERVAL:
                    result = await add_vp(discord_id, VP_AMOUNT)
                    
                    if result.get('success'):
                        total_vp = result.get('totalVP', 0)
                        print(f"[VP] ✅ +{VP_AMOUNT} VP to {member.name} (Total: {total_vp})")
                        rewarded += 1
                        
                        try:
                            await member.send(
                                f"💰 **+{VP_AMOUNT} VP!**\n"
                                f"Total VP: **{total_vp:,}**\n\n"
                                f"Keep staying in <#{VP_CHANNEL_ID}> to earn more!"
                            )
                        except:
                            pass
                    else:
                        print(f"[VP] ❌ Failed to give VP to {member.name}: {result.get('error')}")
                    
                    # Reset timer
                    user_voice_data[discord_id]['vp_start'] = now
        
        if rewarded > 0:
            print(f"[VP TASK] ✅ Rewarded {rewarded} user(s)")
    
    except Exception as e:
        print(f"[VP TASK ERROR] {e}")

@tasks.loop(seconds=GEMS_REFRESH)
async def gems_task():
    """Refresh gems boost for users in Gems channel"""
    try:
        channel = bot.get_channel(GEMS_CHANNEL_ID)
        if not channel:
            print(f"[GEMS TASK] ⚠️ Channel {GEMS_CHANNEL_ID} not found")
            return
        
        if len(channel.members) == 0:
            return  # No one in channel
        
        refreshed = 0
        
        for member in channel.members:
            if member.bot:
                continue
            
            discord_id = str(member.id)
            
            # Refresh boost
            result = await add_gems_boost(discord_id, GEMS_MULTIPLIER, GEMS_REFRESH)
            
            if result.get('success'):
                refreshed += 1
            else:
                print(f"[GEMS] ❌ Failed to refresh boost for {member.name}")
        
        if refreshed > 0:
            print(f"[GEMS TASK] ✅ Refreshed boost for {refreshed} user(s)")
    
    except Exception as e:
        print(f"[GEMS TASK ERROR] {e}")

# ============= COMMANDS =============
@bot.tree.command(name='profile', description='Check your Discord Rewards profile')
async def profile(interaction: discord.Interaction):
    """Show user's VP and boost status"""
    await interaction.response.defer(ephemeral=True)
    
    discord_id = str(interaction.user.id)
    result = await get_profile(discord_id)
    
    if result.get('success'):
        grow_id = result.get('growID', 'Unknown')
        total_vp = result.get('totalVP', 0)
        
        embed = discord.Embed(
            title="🎮 Your Profile",
            color=discord.Color.blue()
        )
        embed.add_field(name="GrowID", value=f"`{grow_id}`", inline=False)
        embed.add_field(name="Total VP Earned", value=f"**{total_vp:,}** VP", inline=False)
        embed.add_field(
            name="How to Earn More",
            value=f"💰 Join <#{VP_CHANNEL_ID}> to earn **{VP_AMOUNT} VP** every **{VP_INTERVAL//60} minutes**\n"
                  f"💎 Join <#{GEMS_CHANNEL_ID}> for **{GEMS_MULTIPLIER}x** gems boost in-game",
            inline=False
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send(
            "❌ **Profile not found**\n\n"
            "Make sure you've linked your Discord account to Growtopia!\n"
            "Your account will be automatically created when you join a voice channel.",
            ephemeral=True
        )

@bot.tree.command(name='rewards', description='Show rewards information')
async def rewards(interaction: discord.Interaction):
    """Show rewards info"""
    embed = discord.Embed(
        title="🎁 Discord Voice Rewards",
        description="Earn rewards by joining voice channels!",
        color=discord.Color.gold()
    )
    
    embed.add_field(
        name="💰 VP (Voice Points)",
        value=f"**Channel:** <#{VP_CHANNEL_ID}>\n"
              f"**Reward:** +{VP_AMOUNT} VP every {VP_INTERVAL//60} minutes\n"
              f"**Usage:** Spend VP in `/vpshop` in-game",
        inline=False
    )
    
    embed.add_field(
        name="💎 Gems Boost",
        value=f"**Channel:** <#{GEMS_CHANNEL_ID}>\n"
              f"**Boost:** {GEMS_MULTIPLIER}x gems from breaking blocks\n"
              f"**Duration:** Active while in channel + {GEMS_DURATION//60} min after leaving",
        inline=False
    )
    
    embed.add_field(
        name="ℹ️ Requirements",
        value="Your Discord account must be linked to Growtopia.\n"
              "Accounts are automatically created when you join a voice channel.",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed)

# ============= HEALTH CHECK =============
async def health_check(request):
    """Health check endpoint for Render"""
    return web.Response(text="OK", status=200)

async def start_http_server():
    """Start HTTP server for Render health checks"""
    app = web.Application()
    app.router.add_get('/', health_check)
    
    port = int(os.getenv('PORT', '10000'))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f'[HTTP] Health check server started on port {port}')

# ============= MAIN =============
async def main():
    """Main function"""
    await start_http_server()
    await bot.start(DISCORD_TOKEN)

if __name__ == '__main__':
    print("=" * 50)
    print("DISCORD VOICE REWARDS BOT - STARTING")
    print("=" * 50)
    print(f"API: {API_BASE_URL}")
    print(f"VP Channel: {VP_CHANNEL_ID}")
    print(f"Gems Channel: {GEMS_CHANNEL_ID}")
    print("=" * 50)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[BOT] Stopped by user")
