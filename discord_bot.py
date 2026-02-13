import discord
from discord import app_commands
from discord.ext import tasks
import aiohttp
import asyncio
import os
from datetime import datetime
from collections import defaultdict
from aiohttp import web
import traceback

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

# ============= API (IMPROVED ERROR HANDLING) =============
async def api_call(endpoint, data):
    async with aiohttp.ClientSession() as session:
        try:
            url = f"{API_BASE_URL}{endpoint}"
            print(f"\n[API] >>> POST {url}")
            print(f"[API] >>> Data: {data}")
            
            async with session.post(
                url, 
                json=data, 
                headers={'Content-Type': 'application/json'},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                status = response.status
                
                # Get response text first
                text = await response.text()
                print(f"[API] <<< Status: {status}")
                print(f"[API] <<< Raw Response: {text[:500]}")
                
                # Handle empty response
                if not text or text.strip() == "":
                    print("[API] ERROR: Empty response from server")
                    return {"success": False, "error": "Server returned empty response"}
                
                # Try to parse JSON
                try:
                    result = await response.json(content_type=None)  # Ignore content-type
                    print(f"[API] <<< Parsed: {result}")
                except Exception as parse_error:
                    print(f"[API] ERROR: JSON parse failed - {parse_error}")
                    print(f"[API] ERROR: Raw text: {text}")
                    return {"success": False, "error": f"Invalid JSON response: {text[:100]}"}
                
                # Handle HTTP errors
                if status == 403:
                    return {"success": False, "error": result.get('error', 'Forbidden')}
                elif status == 400:
                    return {"success": False, "error": result.get('error', 'Bad request')}
                elif status == 404:
                    return {"success": False, "error": result.get('error', 'Not found')}
                elif status >= 400:
                    return {"success": False, "error": f"Server error ({status}): {result.get('error', 'Unknown')}"}
                
                return result
                    
        except asyncio.TimeoutError:
            print(f"[API] ERROR: Request timeout")
            return {"success": False, "error": "Connection timeout - server not responding"}
        except aiohttp.ClientError as e:
            print(f"[API] ERROR: Connection failed - {type(e).__name__}: {e}")
            return {"success": False, "error": f"Connection failed: {str(e)}"}
        except Exception as e:
            print(f"[API] ERROR: Unexpected error - {type(e).__name__}: {e}")
            traceback.print_exc()
            return {"success": False, "error": f"Unexpected error: {str(e)}"}

async def get_profile(discord_id):
    return await api_call('/api/discord/get', {'discordID': str(discord_id)})

async def add_vp(discord_id, amount):
    return await api_call('/api/discord/reward/vp', {
        'discordID': str(discord_id), 
        'amount': amount
    })

async def add_gems_boost(discord_id, multiplier, duration):
    return await api_call('/api/discord/reward/gems', {
        'discordID': str(discord_id), 
        'multiplier': multiplier, 
        'duration': duration
    })

# ============= BUTTON VIEW =============
class LinkButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="🔗 Link Account", style=discord.ButtonStyle.success, custom_id="vp_link_btn")
    async def link_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = LinkModal()
        await interaction.response.send_modal(modal)

class LinkModal(discord.ui.Modal, title="Link Your Account"):
    username_input = discord.ui.TextInput(
        label="GrowID (Username)",
        placeholder="YourGrowID",
        min_length=3,
        max_length=18,
        style=discord.TextStyle.short
    )
    
    code_input = discord.ui.TextInput(
        label="6-Digit Code from /linkvp",
        placeholder="123456",
        min_length=6,
        max_length=6,
        style=discord.TextStyle.short
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        username = self.username_input.value.strip()
        code = self.code_input.value.strip()
        
        print(f"\n{'='*60}")
        print(f"[LINK] New link attempt")
        print(f"[LINK] User: {interaction.user.name} ({interaction.user.id})")
        print(f"[LINK] Username: {username}")
        print(f"[LINK] Code: {code}")
        print(f"{'='*60}\n")
        
        # Call API
        result = await api_call('/api/discord/link', {
            'username': username,
            'code': code
        })
        
        print(f"\n[LINK] Result: {result}\n")
        
        if result.get('success'):
            growID = result.get('growID', username)
            embed = discord.Embed(
                title="✅ Account Linked!",
                description=f"Successfully linked to: **{growID}**",
                color=discord.Color.green()
            )
            embed.add_field(
                name="💰 Earn VP",
                value=f"Join <#{VP_CHANNEL_ID}> to earn **{VP_AMOUNT} VP** every **{VP_INTERVAL//60} minutes**",
                inline=False
            )
            embed.add_field(
                name="💎 Gems Boost",
                value=f"Join <#{GEMS_CHANNEL_ID}> for **{GEMS_MULTIPLIER}x** gems boost in-game",
                inline=False
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            error = result.get('error', 'Unknown error - server did not respond properly')
            
            embed = discord.Embed(
                title="❌ Link Failed",
                description=f"**Error:** {error}",
                color=discord.Color.red()
            )
            embed.add_field(
                name="📝 Steps to Link",
                value=(
                    "1. Type `/linkvp` in-game\n"
                    "2. Copy your **GrowID** (username)\n"
                    "3. Copy the **6-digit code**\n"
                    "4. Enter both here within 5 minutes"
                ),
                inline=False
            )
            embed.add_field(
                name="❓ Common Issues",
                value=(
                    "• Code expired? Get a new one with `/linkvp`\n"
                    "• Check your GrowID spelling\n"
                    "• Make sure Discord is linked in-game first"
                ),
                inline=False
            )
            
            await interaction.followup.send(embed=embed, ephemeral=True)

# ============= EVENTS =============
@bot.event
async def on_ready():
    print(f'\n{"="*60}')
    print(f'[BOT] Logged in as {bot.user.name} ({bot.user.id})')
    print(f'[CONFIG] API: {API_BASE_URL}')
    print(f'[CONFIG] VP Channel: {VP_CHANNEL_ID}')
    print(f'[CONFIG] Gems Channel: {GEMS_CHANNEL_ID}')
    print(f'{"="*60}\n')
    
    # Register persistent view
    bot.add_view(LinkButton())
    
    if not vp_task.is_running():
        vp_task.start()
    if not gems_task.is_running():
        gems_task.start()
    
    print('[BOT] ✅ Ready!\n')

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    
    discord_id = str(member.id)
    now = datetime.now()
    
    # VP Channel
    if after.channel and after.channel.id == VP_CHANNEL_ID:
        if user_voice_data[discord_id]['vp_start'] is None:
            user_voice_data[discord_id]['vp_start'] = now
            print(f"[VP] ✅ {member.name} joined")
    elif before.channel and before.channel.id == VP_CHANNEL_ID:
        user_voice_data[discord_id]['vp_start'] = None
        print(f"[VP] ❌ {member.name} left")
    
    # Gems Channel
    if after.channel and after.channel.id == GEMS_CHANNEL_ID:
        if user_voice_data[discord_id]['gems_start'] is None:
            user_voice_data[discord_id]['gems_start'] = now
            print(f"[GEMS] ✅ {member.name} joined")
            
            result = await add_gems_boost(discord_id, GEMS_MULTIPLIER, GEMS_DURATION)
            if result.get('success'):
                try:
                    await member.send(
                        f"💎 **Gems Boost Activated!**\n"
                        f"Multiplier: **{GEMS_MULTIPLIER}x**\n"
                        f"Duration: **{GEMS_DURATION//60} minutes**"
                    )
                except:
                    pass
    elif before.channel and before.channel.id == GEMS_CHANNEL_ID:
        user_voice_data[discord_id]['gems_start'] = None
        print(f"[GEMS] ❌ {member.name} left")

# ============= TASKS =============
@tasks.loop(seconds=VP_INTERVAL)
async def vp_task():
    try:
        channel = bot.get_channel(VP_CHANNEL_ID)
        if not channel or len(channel.members) == 0:
            return
        
        now = datetime.now()
        
        for member in channel.members:
            if member.bot:
                continue
            
            discord_id = str(member.id)
            start_time = user_voice_data[discord_id]['vp_start']
            
            if start_time and (now - start_time).total_seconds() >= VP_INTERVAL:
                result = await add_vp(discord_id, VP_AMOUNT)
                
                if result.get('success'):
                    total_vp = result.get('totalVP', 0)
                    print(f"[VP] ✅ +{VP_AMOUNT} to {member.name} (Total: {total_vp})")
                    try:
                        await member.send(f"💰 **+{VP_AMOUNT} VP!** Total: **{total_vp:,}**")
                    except:
                        pass
                else:
                    print(f"[VP] ❌ Failed for {member.name}: {result.get('error')}")
                
                user_voice_data[discord_id]['vp_start'] = now
    except Exception as e:
        print(f"[VP ERROR] {e}")
        traceback.print_exc()

@tasks.loop(seconds=GEMS_REFRESH)
async def gems_task():
    try:
        channel = bot.get_channel(GEMS_CHANNEL_ID)
        if not channel or len(channel.members) == 0:
            return
        
        for member in channel.members:
            if not member.bot:
                await add_gems_boost(str(member.id), GEMS_MULTIPLIER, GEMS_REFRESH)
    except Exception as e:
        print(f"[GEMS ERROR] {e}")
        traceback.print_exc()

# ============= COMMANDS =============
@bot.tree.command(name='sendlink', description='[ADMIN] Send link button')
@app_commands.checks.has_permissions(administrator=True)
async def sendlink(interaction: discord.Interaction):
    """Send the link button to current channel"""
    embed = discord.Embed(
        title="🎮 Link Your Account",
        description="Connect your Growtopia account to earn Discord rewards!",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="🔗 How to Link",
        value=(
            "1. Type `/linkvp` in-game\n"
            "2. Get your **GrowID** and **6-digit code**\n"
            "3. Click the button below\n"
            "4. Enter both within 5 minutes"
        ),
        inline=False
    )
    embed.add_field(
        name="🎁 Rewards",
        value=(
            f"💰 **VP**: +{VP_AMOUNT} every {VP_INTERVAL//60} min in <#{VP_CHANNEL_ID}>\n"
            f"💎 **Gems**: {GEMS_MULTIPLIER}x boost in <#{GEMS_CHANNEL_ID}>"
        ),
        inline=False
    )
    
    await interaction.channel.send(embed=embed, view=LinkButton())
    await interaction.response.send_message("✅ Button sent!", ephemeral=True)

@bot.tree.command(name='profile', description='Check your VP profile')
async def profile(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    result = await get_profile(str(interaction.user.id))
    
    if result.get('success'):
        embed = discord.Embed(title="🎮 Your Profile", color=discord.Color.blue())
        embed.add_field(name="GrowID", value=f"`{result.get('growID')}`", inline=False)
        embed.add_field(name="Total VP", value=f"**{result.get('totalVP', 0):,}** VP", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send(
            "❌ **Not Linked**\n\nUse `/linkvp` in-game and click the link button!",
            ephemeral=True
        )

@bot.tree.command(name='rewards', description='Show rewards info')
async def rewards(interaction: discord.Interaction):
    embed = discord.Embed(title="🎁 Voice Rewards", color=discord.Color.gold())
    embed.add_field(
        name="💰 VP",
        value=f"<#{VP_CHANNEL_ID}>\n+{VP_AMOUNT} VP every {VP_INTERVAL//60} min",
        inline=False
    )
    embed.add_field(
        name="💎 Gems",
        value=f"<#{GEMS_CHANNEL_ID}>\n{GEMS_MULTIPLIER}x boost",
        inline=False
    )
    await interaction.response.send_message(embed=embed)

# ============= HEALTH CHECK =============
async def health_check(request):
    return web.Response(text="OK", status=200)

async def start_http_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    
    port = int(os.getenv('PORT', '10000'))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f'[HTTP] Health check on port {port}\n')

# ============= MAIN =============
async def main():
    await start_http_server()
    await bot.start(DISCORD_TOKEN)

if __name__ == '__main__':
    print("="*60)
    print("DISCORD VP BOT - ENHANCED ERROR HANDLING")
    print("="*60)
    print()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[BOT] Stopped")
