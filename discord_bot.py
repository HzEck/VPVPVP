import discord
from discord import app_commands
from discord.ext import tasks
import asyncio
import os
from datetime import datetime, timedelta
from collections import defaultdict
from aiohttp import web
import json

# ============= CONFIG =============
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN', 'YOUR_BOT_TOKEN')
WEBHOOK_PORT = int(os.getenv('WEBHOOK_PORT', '10000'))

# Voice channels
VP_CHANNEL_ID = int(os.getenv('VP_CHANNEL_ID', '1470057279511466045'))
GEMS_CHANNEL_ID = int(os.getenv('GEMS_CHANNEL_ID', '1470057299631411444'))

# Reward settings
VP_AMOUNT = 10
VP_INTERVAL = 300  # 5 minutes
GEMS_MULTIPLIER = 1.05
GEMS_DURATION = 3600
GEMS_REFRESH = 60

# ============= DATA STORAGE (IN-MEMORY) =============
# Oyundan gelen linkler
pending_links = {}  # code -> {growid, timestamp}
linked_accounts = {}  # discord_id -> {growid, total_vp, linked_at}
reverse_links = {}  # growid_lower -> discord_id

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

# ============= WEBHOOK HANDLERS =============
async def handle_link_request(request):
    """Oyundan link isteği geldi"""
    try:
        data = await request.json()
        growid = data.get('growid')
        code = data.get('code')
        
        print(f"\n[WEBHOOK] Link request from game")
        print(f"[WEBHOOK] GrowID: {growid}")
        print(f"[WEBHOOK] Code: {code}")
        
        if not growid or not code:
            return web.json_response({
                'success': False,
                'error': 'Missing growid or code'
            })
        
        # Store pending link
        pending_links[code.upper()] = {
            'growid': growid,
            'timestamp': datetime.now()
        }
        
        print(f"[WEBHOOK] ✅ Stored pending link: {code} -> {growid}")
        
        return web.json_response({
            'success': True,
            'message': 'Code registered. Use /linkvp in Discord.'
        })
        
    except Exception as e:
        print(f"[WEBHOOK ERROR] {e}")
        return web.json_response({
            'success': False,
            'error': str(e)
        }, status=500)

async def handle_vp_check(request):
    """Oyundan VP kontrolü"""
    try:
        data = await request.json()
        growid = data.get('growid')
        
        growid_lower = growid.lower() if growid else None
        discord_id = reverse_links.get(growid_lower)
        
        if not discord_id or discord_id not in linked_accounts:
            return web.json_response({
                'success': False,
                'error': 'Not linked'
            })
        
        account = linked_accounts[discord_id]
        
        return web.json_response({
            'success': True,
            'growid': account['growid'],
            'total_vp': account['total_vp'],
            'discord_id': discord_id
        })
        
    except Exception as e:
        print(f"[WEBHOOK ERROR] {e}")
        return web.json_response({
            'success': False,
            'error': str(e)
        }, status=500)

async def handle_gems_callback(request):
    """Oyundan gems callback - boost kontrolü"""
    try:
        data = await request.json()
        growid = data.get('growid')
        amount = data.get('amount', 0)
        
        growid_lower = growid.lower() if growid else None
        discord_id = reverse_links.get(growid_lower)
        
        if not discord_id:
            return web.json_response({
                'success': True,
                'bonus': 0,
                'message': 'Not linked'
            })
        
        # Check if user in gems channel
        channel = bot.get_channel(GEMS_CHANNEL_ID)
        if channel:
            for member in channel.members:
                if str(member.id) == discord_id:
                    # Calculate bonus
                    bonus = int(amount * (GEMS_MULTIPLIER - 1))
                    
                    return web.json_response({
                        'success': True,
                        'bonus': bonus,
                        'multiplier': GEMS_MULTIPLIER
                    })
        
        return web.json_response({
            'success': True,
            'bonus': 0,
            'message': 'Not in gems channel'
        })
        
    except Exception as e:
        print(f"[WEBHOOK ERROR] {e}")
        return web.json_response({
            'success': False,
            'error': str(e)
        }, status=500)

async def start_webhook_server():
    """Webhook server başlat"""
    app = web.Application()
    
    # Routes
    app.router.add_post('/webhook/link', handle_link_request)
    app.router.add_post('/webhook/vp/check', handle_vp_check)
    app.router.add_post('/webhook/gems/check', handle_gems_callback)
    app.router.add_get('/', lambda req: web.Response(text="VP Bot Webhook Running!"))
    app.router.add_get('/health', lambda req: web.Response(text="OK"))
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', WEBHOOK_PORT)
    await site.start()
    
    print(f'\n[WEBHOOK] Server running on port {WEBHOOK_PORT}')
    print(f'[WEBHOOK] Endpoints:')
    print(f'[WEBHOOK]   POST /webhook/link')
    print(f'[WEBHOOK]   POST /webhook/vp/check')
    print(f'[WEBHOOK]   POST /webhook/gems/check\n')

# ============= CLEANUP TASK =============
@tasks.loop(seconds=60)
async def cleanup_expired_links():
    """Expired kodları temizle"""
    now = datetime.now()
    expired = []
    
    for code, data in pending_links.items():
        if (now - data['timestamp']).total_seconds() > 300:  # 5 minutes
            expired.append(code)
    
    for code in expired:
        del pending_links[code]
    
    if expired:
        print(f"[CLEANUP] Removed {len(expired)} expired codes")

# ============= EVENTS =============
@bot.event
async def on_ready():
    print(f'\n{"="*50}')
    print(f'  DISCORD VP REWARDS BOT - WEBHOOK MODE')
    print(f'{"="*50}')
    print(f'[BOT] ✅ Logged in as {bot.user.name}')
    print(f'[BOT] 💰 VP Channel: {VP_CHANNEL_ID}')
    print(f'[BOT] 💎 Gems Channel: {GEMS_CHANNEL_ID}')
    print(f'[BOT] 🔗 Webhook Port: {WEBHOOK_PORT}')
    print(f'{"="*50}\n')
    
    # Tasks
    if not vp_task.is_running():
        vp_task.start()
    if not cleanup_expired_links.is_running():
        cleanup_expired_links.start()
    
    print('[BOT] 🚀 Ready!\n')

@bot.event
async def on_voice_state_update(member, before, after):
    """Ses kanalı tracking"""
    if member.bot:
        return
    
    discord_id = str(member.id)
    now = datetime.now()
    
    # VP channel
    if after.channel and after.channel.id == VP_CHANNEL_ID:
        if user_voice_data[discord_id]['vp_start'] is None:
            user_voice_data[discord_id]['vp_start'] = now
            print(f"[VP] {member.name} joined VP channel")
    elif before.channel and before.channel.id == VP_CHANNEL_ID:
        user_voice_data[discord_id]['vp_start'] = None
        print(f"[VP] {member.name} left VP channel")
    
    # Gems channel
    if after.channel and after.channel.id == GEMS_CHANNEL_ID:
        if user_voice_data[discord_id]['gems_start'] is None:
            user_voice_data[discord_id]['gems_start'] = now
            print(f"[GEMS] {member.name} joined Gems channel")
            
            # Check if linked
            if discord_id in linked_accounts:
                try:
                    await member.send(
                        f"💎 **Gems Boost Active!**\n"
                        f"• Multiplier: **{GEMS_MULTIPLIER}x**\n"
                        f"• While you're in the channel"
                    )
                except:
                    pass
    elif before.channel and before.channel.id == GEMS_CHANNEL_ID:
        user_voice_data[discord_id]['gems_start'] = None
        print(f"[GEMS] {member.name} left Gems channel")

# ============= VP TASK =============
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
            
            # Check if linked
            if discord_id not in linked_accounts:
                continue
            
            start_time = user_voice_data[discord_id]['vp_start']
            
            if start_time:
                elapsed = (now - start_time).total_seconds()
                
                if elapsed >= VP_INTERVAL:
                    # Add VP
                    account = linked_accounts[discord_id]
                    account['total_vp'] += VP_AMOUNT
                    
                    print(f"[VP] ✅ Gave {VP_AMOUNT} VP to {member.name} ({account['growid']})")
                    
                    try:
                        await member.send(
                            f"💰 **VP Earned!**\n"
                            f"• Amount: **+{VP_AMOUNT} VP**\n"
                            f"• Total: **{account['total_vp']}**\n"
                            f"• Time: **{int(elapsed / 60)} minutes**"
                        )
                    except:
                        pass
                    
                    # Reset timer
                    user_voice_data[discord_id]['vp_start'] = now
    
    except Exception as e:
        print(f"[VP ERROR] {e}")

# ============= COMMANDS =============
@bot.tree.command(name='linkvp', description='Link your Growtopia account')
@app_commands.describe(code='6-digit code from /linkvp command in-game')
async def linkvp(interaction: discord.Interaction, code: str):
    """Link account - WEBHOOK MODE"""
    await interaction.response.defer(ephemeral=True)
    
    code = code.upper().strip()
    discord_id = str(interaction.user.id)
    
    print(f"\n[LINK] Discord user: {interaction.user.name}")
    print(f"[LINK] Code: {code}")
    print(f"[LINK] Discord ID: {discord_id}")
    
    # Check if already linked
    if discord_id in linked_accounts:
        account = linked_accounts[discord_id]
        await interaction.followup.send(
            f"❌ **Already Linked**\n"
            f"Your Discord is already linked to: `{account['growid']}`\n"
            f"Total VP: **{account['total_vp']}**",
            ephemeral=True
        )
        return
    
    # Check pending links
    if code not in pending_links:
        await interaction.followup.send(
            f"❌ **Invalid or Expired Code**\n\n"
            f"**Steps:**\n"
            f"1. Type `/linkvp` in Growtopia\n"
            f"2. Copy the 6-digit code\n"
            f"3. Use `/linkvp <code>` here within 5 minutes\n\n"
            f"**Note:** Code must be used within 5 minutes!",
            ephemeral=True
        )
        return
    
    pending = pending_links[code]
    growid = pending['growid']
    growid_lower = growid.lower()
    
    # Check if growid already linked
    if growid_lower in reverse_links:
        existing_discord = reverse_links[growid_lower]
        await interaction.followup.send(
            f"❌ **GrowID Already Linked**\n"
            f"`{growid}` is already linked to another Discord account.",
            ephemeral=True
        )
        return
    
    # Create link!
    linked_accounts[discord_id] = {
        'growid': growid,
        'total_vp': 0,
        'linked_at': datetime.now()
    }
    reverse_links[growid_lower] = discord_id
    
    # Remove from pending
    del pending_links[code]
    
    print(f"[LINK] ✅ Success! {growid} <-> Discord:{discord_id}")
    
    embed = discord.Embed(
        title="✅ Account Linked!",
        description=f"Successfully linked your accounts!",
        color=discord.Color.green()
    )
    embed.add_field(name="Discord", value=interaction.user.mention, inline=False)
    embed.add_field(name="GrowID", value=f"`{growid}`", inline=False)
    embed.add_field(
        name="🎁 Start Earning",
        value=f"• Join <#{VP_CHANNEL_ID}> → **{VP_AMOUNT} VP** every {VP_INTERVAL // 60} min\n"
              f"• Join <#{GEMS_CHANNEL_ID}> → **{GEMS_MULTIPLIER}x gems boost**",
        inline=False
    )
    
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name='profile', description='Check your stats')
async def profile(interaction: discord.Interaction):
    """Profile"""
    await interaction.response.defer(ephemeral=True)
    
    discord_id = str(interaction.user.id)
    
    if discord_id not in linked_accounts:
        await interaction.followup.send(
            "❌ **Not Linked**\n"
            "Use `/linkvp <code>` to link your account!\n"
            "Get code with `/linkvp` in Growtopia.",
            ephemeral=True
        )
        return
    
    account = linked_accounts[discord_id]
    
    embed = discord.Embed(
        title="🎮 Your Profile",
        color=discord.Color.blue()
    )
    embed.add_field(name="Discord", value=interaction.user.mention, inline=False)
    embed.add_field(name="GrowID", value=f"`{account['growid']}`", inline=False)
    embed.add_field(name="Total VP", value=f"**{account['total_vp']:,}**", inline=False)
    
    # Check if in voice
    channel = bot.get_channel(VP_CHANNEL_ID)
    if channel:
        for member in channel.members:
            if str(member.id) == discord_id:
                embed.add_field(name="Status", value="🟢 **In VP Channel**", inline=False)
                break
    
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name='rewards', description='View reward system')
async def rewards(interaction: discord.Interaction):
    """Rewards info"""
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
              f"• Active while you're in channel",
        inline=False
    )
    
    embed.add_field(
        name="📝 How to Link",
        value="1. Type `/linkvp` in Growtopia\n"
              "2. Copy the 6-digit code\n"
              "3. Use `/linkvp <code>` here\n"
              "4. Join voice channels!",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='help', description='Show commands')
async def help_cmd(interaction: discord.Interaction):
    """Help"""
    embed = discord.Embed(
        title="🤖 Commands",
        color=discord.Color.purple()
    )
    
    embed.add_field(name="/linkvp <code>", value="Link your account", inline=False)
    embed.add_field(name="/profile", value="View your stats", inline=False)
    embed.add_field(name="/rewards", value="View rewards info", inline=False)
    embed.add_field(name="/help", value="Show this message", inline=False)
    
    await interaction.response.send_message(embed=embed)

# ============= MAIN =============
async def main():
    await start_webhook_server()
    await bot.start(DISCORD_TOKEN)

if __name__ == '__main__':
    if DISCORD_TOKEN == 'YOUR_BOT_TOKEN':
        print("[ERROR] Set DISCORD_TOKEN!")
    else:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            print("\n[BOT] Shutting down...")
