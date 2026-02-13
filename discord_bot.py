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
VP_INTERVAL = 5  # 3 minutes (was 5)
GEMS_MULTIPLIER = 1.05

# ============= DATA STORAGE =============
pending_links = {}  # code -> {growid, timestamp}
linked_accounts = {}  # discord_id -> {growid, total_vp, linked_at, last_vp_time}
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
user_voice_data = defaultdict(lambda: {'vp_start': None, 'gems_active': False})

# ============= WEBHOOK HANDLERS =============
async def handle_link_request(request):
    """Link request from game"""
    try:
        data = await request.json()
        growid = data.get('growid')
        code = data.get('code')
        
        print(f"\n[WEBHOOK] 🔗 Link request")
        print(f"[WEBHOOK] GrowID: {growid}")
        print(f"[WEBHOOK] Code: {code}")
        
        if not growid or not code:
            return web.json_response({
                'success': False,
                'error': 'Missing data'
            })
        
        growid_lower = growid.lower()
        
        # Check if already linked
        if growid_lower in reverse_links:
            discord_id = reverse_links[growid_lower]
            account = linked_accounts.get(discord_id)
            
            return web.json_response({
                'success': False,
                'error': 'already_linked',
                'discord_id': discord_id,
                'total_vp': account.get('total_vp', 0) if account else 0
            })
        
        # Store pending link
        pending_links[code.upper()] = {
            'growid': growid,
            'timestamp': datetime.now()
        }
        
        print(f"[WEBHOOK] ✅ Stored: {code} -> {growid}")
        
        return web.json_response({
            'success': True,
            'message': 'Code registered'
        })
        
    except Exception as e:
        print(f"[WEBHOOK ERROR] {e}")
        return web.json_response({'success': False, 'error': str(e)}, status=500)

async def handle_vp_check(request):
    """VP check from game"""
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
        return web.json_response({'success': False, 'error': str(e)}, status=500)

async def handle_vp_spend(request):
    """Spend VP from game"""
    try:
        data = await request.json()
        growid = data.get('growid')
        amount = data.get('amount', 0)
        
        print(f"[WEBHOOK] 💸 VP Spend request")
        print(f"[WEBHOOK] GrowID: {growid} | Amount: {amount}")
        
        growid_lower = growid.lower() if growid else None
        discord_id = reverse_links.get(growid_lower)
        
        if not discord_id or discord_id not in linked_accounts:
            return web.json_response({
                'success': False,
                'error': 'Not linked'
            })
        
        account = linked_accounts[discord_id]
        
        if account['total_vp'] < amount:
            return web.json_response({
                'success': False,
                'error': 'Insufficient VP',
                'current': account['total_vp']
            })
        
        # Deduct VP
        account['total_vp'] -= amount
        
        print(f"[WEBHOOK] ✅ Spent {amount} VP | Remaining: {account['total_vp']}")
        
        return web.json_response({
            'success': True,
            'spent': amount,
            'remaining': account['total_vp']
        })
        
    except Exception as e:
        return web.json_response({'success': False, 'error': str(e)}, status=500)

async def handle_gems_check(request):
    """Check gems boost status"""
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
                'active': False
            })
        
        # Check if in gems channel
        gems_active = user_voice_data[discord_id]['gems_active']
        
        if gems_active:
            bonus = int(amount * (GEMS_MULTIPLIER - 1))
            return web.json_response({
                'success': True,
                'bonus': bonus,
                'multiplier': GEMS_MULTIPLIER,
                'active': True
            })
        
        return web.json_response({
            'success': True,
            'bonus': 0,
            'active': False
        })
        
    except Exception as e:
        return web.json_response({'success': False, 'error': str(e)}, status=500)

async def start_webhook_server():
    """Start webhook server"""
    app = web.Application()
    
    app.router.add_post('/webhook/link', handle_link_request)
    app.router.add_post('/webhook/vp/check', handle_vp_check)
    app.router.add_post('/webhook/vp/spend', handle_vp_spend)
    app.router.add_post('/webhook/gems/check', handle_gems_check)
    app.router.add_get('/', lambda req: web.Response(text="VP Bot Webhook Running!"))
    app.router.add_get('/health', lambda req: web.Response(text="OK"))
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', WEBHOOK_PORT)
    await site.start()
    
    print(f'\n[WEBHOOK] 🚀 Server running on port {WEBHOOK_PORT}')

# ============= CLEANUP =============
@tasks.loop(seconds=60)
async def cleanup_expired_links():
    """Clean expired codes"""
    now = datetime.now()
    expired = [code for code, data in pending_links.items() 
               if (now - data['timestamp']).total_seconds() > 300]
    
    for code in expired:
        del pending_links[code]
    
    if expired:
        print(f"[CLEANUP] Removed {len(expired)} expired codes")

# ============= EVENTS =============
@bot.event
async def on_ready():
    print(f'\n{"="*60}')
    print(f'  🎮 DISCORD VP REWARDS BOT - PROFESSIONAL MODE')
    print(f'{"="*60}')
    print(f'[BOT] ✅ Logged in as {bot.user.name}')
    print(f'[BOT] 💰 VP Channel: {VP_CHANNEL_ID}')
    print(f'[BOT] 💎 Gems Channel: {GEMS_CHANNEL_ID}')
    print(f'[BOT] ⏱️  VP Interval: {VP_INTERVAL}s ({VP_INTERVAL//60} min)')
    print(f'[BOT] 🔗 Webhook: Port {WEBHOOK_PORT}')
    print(f'{"="*60}\n')
    
    if not vp_task.is_running():
        vp_task.start()
    if not cleanup_expired_links.is_running():
        cleanup_expired_links.start()
    
    print('[BOT] 🚀 Ready!\n')

@bot.event
async def on_voice_state_update(member, before, after):
    """Voice channel tracking"""
    if member.bot:
        return
    
    discord_id = str(member.id)
    now = datetime.now()
    
    # VP Channel
    if after.channel and after.channel.id == VP_CHANNEL_ID:
        if user_voice_data[discord_id]['vp_start'] is None:
            user_voice_data[discord_id]['vp_start'] = now
            print(f"[VOICE] 💰 {member.name} joined VP channel")
    elif before.channel and before.channel.id == VP_CHANNEL_ID:
        user_voice_data[discord_id]['vp_start'] = None
        print(f"[VOICE] 💰 {member.name} left VP channel")
    
    # Gems Channel - Active only when in channel
    if after.channel and after.channel.id == GEMS_CHANNEL_ID:
        if not user_voice_data[discord_id]['gems_active']:
            user_voice_data[discord_id]['gems_active'] = True
            print(f"[VOICE] 💎 {member.name} joined Gems channel - BOOST ACTIVE")
            
            if discord_id in linked_accounts:
                try:
                    embed = discord.Embed(
                        title="💎 Gems Boost Activated!",
                        description="Your gems multiplier is now active!",
                        color=discord.Color.green()
                    )
                    embed.add_field(
                        name="Multiplier",
                        value=f"**{GEMS_MULTIPLIER}x**",
                        inline=True
                    )
                    embed.add_field(
                        name="Duration",
                        value="While in channel",
                        inline=True
                    )
                    embed.set_footer(text="Leave channel to deactivate")
                    
                    await member.send(embed=embed)
                except:
                    pass
                    
    elif before.channel and before.channel.id == GEMS_CHANNEL_ID:
        user_voice_data[discord_id]['gems_active'] = False
        print(f"[VOICE] 💎 {member.name} left Gems channel - BOOST DEACTIVATED")

# ============= VP TASK =============
@tasks.loop(seconds=VP_INTERVAL)
async def vp_task():
    """Award VP every interval"""
    try:
        channel = bot.get_channel(VP_CHANNEL_ID)
        if not channel:
            return
        
        now = datetime.now()
        
        for member in channel.members:
            if member.bot:
                continue
            
            discord_id = str(member.id)
            
            if discord_id not in linked_accounts:
                continue
            
            start_time = user_voice_data[discord_id]['vp_start']
            
            if start_time:
                elapsed = (now - start_time).total_seconds()
                
                if elapsed >= VP_INTERVAL:
                    # Award VP
                    account = linked_accounts[discord_id]
                    account['total_vp'] += VP_AMOUNT
                    account['last_vp_time'] = now
                    
                    print(f"[VP] ✅ Awarded {VP_AMOUNT} VP to {member.name} ({account['growid']})")
                    
                    # Send professional DM
                    try:
                        embed = discord.Embed(
                            title="💰 VP Earned!",
                            description=f"You earned **{VP_AMOUNT} VP** for staying in the voice channel!",
                            color=discord.Color.gold()
                        )
                        embed.add_field(
                            name="Amount Earned",
                            value=f"**+{VP_AMOUNT} VP**",
                            inline=True
                        )
                        embed.add_field(
                            name="Total VP",
                            value=f"**{account['total_vp']:,} VP**",
                            inline=True
                        )
                        embed.add_field(
                            name="Time in Channel",
                            value=f"{int(elapsed / 60)} minutes",
                            inline=True
                        )
                        embed.add_field(
                            name="GrowID",
                            value=f"`{account['growid']}`",
                            inline=False
                        )
                        embed.set_footer(text="Stay in channel to keep earning!")
                        embed.timestamp = datetime.utcnow()
                        
                        await member.send(embed=embed)
                    except Exception as e:
                        print(f"[VP] ⚠️ Could not DM {member.name}: {e}")
                    
                    # Reset timer
                    user_voice_data[discord_id]['vp_start'] = now
    
    except Exception as e:
        print(f"[VP ERROR] {e}")

# ============= COMMANDS =============
@bot.tree.command(name='linkvp', description='🔗 Link your Growtopia account')
@app_commands.describe(code='6-digit code from /linkvp in-game')
async def linkvp(interaction: discord.Interaction, code: str):
    """Link account"""
    await interaction.response.defer(ephemeral=True)
    
    code = code.upper().strip()
    discord_id = str(interaction.user.id)
    
    print(f"\n[LINK] 🔗 {interaction.user.name} | Code: {code}")
    
    # Already linked?
    if discord_id in linked_accounts:
        account = linked_accounts[discord_id]
        
        embed = discord.Embed(
            title="⚠️ Already Linked",
            description="Your Discord account is already linked!",
            color=discord.Color.orange()
        )
        embed.add_field(name="GrowID", value=f"`{account['growid']}`", inline=False)
        embed.add_field(name="Total VP", value=f"**{account['total_vp']:,}**", inline=True)
        embed.add_field(
            name="Linked Since",
            value=f"<t:{int(account['linked_at'].timestamp())}:R>",
            inline=True
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    # Check code
    if code not in pending_links:
        embed = discord.Embed(
            title="❌ Invalid Code",
            description="This code doesn't exist or has expired.",
            color=discord.Color.red()
        )
        embed.add_field(
            name="📝 Steps to Link",
            value="1. Type `/linkvp` in Growtopia\n"
                  "2. Copy the 6-digit code\n"
                  "3. Use `/linkvp <code>` here within 5 minutes",
            inline=False
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    pending = pending_links[code]
    growid = pending['growid']
    growid_lower = growid.lower()
    
    # Check if GrowID already linked
    if growid_lower in reverse_links:
        embed = discord.Embed(
            title="❌ GrowID Already Linked",
            description=f"`{growid}` is already linked to another Discord account.",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    # Link!
    linked_accounts[discord_id] = {
        'growid': growid,
        'total_vp': 0,
        'linked_at': datetime.now(),
        'last_vp_time': None
    }
    reverse_links[growid_lower] = discord_id
    del pending_links[code]
    
    print(f"[LINK] ✅ Success! {growid} <-> {discord_id}")
    
    embed = discord.Embed(
        title="✅ Account Linked Successfully!",
        description="Your accounts are now connected!",
        color=discord.Color.green()
    )
    embed.add_field(name="Discord", value=interaction.user.mention, inline=False)
    embed.add_field(name="GrowID", value=f"`{growid}`", inline=False)
    embed.add_field(
        name="💰 VP Rewards",
        value=f"Join <#{VP_CHANNEL_ID}>\n"
              f"Earn **{VP_AMOUNT} VP** every **{VP_INTERVAL // 60} minutes**",
        inline=False
    )
    embed.add_field(
        name="💎 Gems Boost",
        value=f"Join <#{GEMS_CHANNEL_ID}>\n"
              f"Get **{GEMS_MULTIPLIER}x gems** while in channel",
        inline=False
    )
    embed.set_footer(text="Use /profile to check your stats anytime!")
    embed.timestamp = datetime.utcnow()
    
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name='profile', description='📊 Check your account stats')
async def profile(interaction: discord.Interaction):
    """View profile"""
    await interaction.response.defer(ephemeral=True)
    
    discord_id = str(interaction.user.id)
    
    if discord_id not in linked_accounts:
        embed = discord.Embed(
            title="❌ Not Linked",
            description="You haven't linked your account yet!",
            color=discord.Color.red()
        )
        embed.add_field(
            name="How to Link",
            value="1. Type `/linkvp` in Growtopia\n"
                  "2. Use `/linkvp <code>` here",
            inline=False
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    account = linked_accounts[discord_id]
    
    # Check voice status
    vp_status = "❌ Not in channel"
    gems_status = "❌ Not active"
    
    vp_channel = bot.get_channel(VP_CHANNEL_ID)
    if vp_channel:
        for member in vp_channel.members:
            if str(member.id) == discord_id:
                vp_status = "✅ Earning VP"
                break
    
    if user_voice_data[discord_id]['gems_active']:
        gems_status = "✅ Active"
    
    embed = discord.Embed(
        title="📊 Your Profile",
        description=f"Stats for {interaction.user.mention}",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.add_field(name="GrowID", value=f"`{account['growid']}`", inline=False)
    embed.add_field(name="Total VP", value=f"**{account['total_vp']:,} VP**", inline=True)
    embed.add_field(
        name="Linked Since",
        value=f"<t:{int(account['linked_at'].timestamp())}:R>",
        inline=True
    )
    embed.add_field(name="VP Status", value=vp_status, inline=True)
    embed.add_field(name="Gems Boost", value=gems_status, inline=True)
    
    if account.get('last_vp_time'):
        embed.add_field(
            name="Last VP",
            value=f"<t:{int(account['last_vp_time'].timestamp())}:R>",
            inline=True
        )
    
    embed.set_footer(text="Use VP with /vp command in-game")
    embed.timestamp = datetime.utcnow()
    
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name='rewards', description='🎁 View reward system info')
async def rewards(interaction: discord.Interaction):
    """Rewards info"""
    embed = discord.Embed(
        title="🎁 Voice Rewards System",
        description="Earn rewards by joining voice channels!",
        color=discord.Color.gold()
    )
    
    embed.add_field(
        name="💰 VP Channel",
        value=f"<#{VP_CHANNEL_ID}>\n"
              f"• Earn **{VP_AMOUNT} VP** every **{VP_INTERVAL // 60} minutes**\n"
              f"• Spend VP with `/vp` command in-game\n"
              f"• Get DM notifications when you earn VP",
        inline=False
    )
    
    embed.add_field(
        name="💎 Gems Boost Channel",
        value=f"<#{GEMS_CHANNEL_ID}>\n"
              f"• Get **{GEMS_MULTIPLIER}x gems** multiplier\n"
              f"• Active ONLY while in channel\n"
              f"• Automatically deactivates when you leave",
        inline=False
    )
    
    embed.add_field(
        name="📝 How to Start",
        value="1. Type `/linkvp` in Growtopia\n"
              "2. Copy the 6-digit code\n"
              "3. Use `/linkvp <code>` here\n"
              "4. Join voice channels to earn!",
        inline=False
    )
    
    embed.set_footer(text="Use /profile to check your stats")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='help', description='❓ Show all commands')
async def help_cmd(interaction: discord.Interaction):
    """Help menu"""
    embed = discord.Embed(
        title="🤖 Bot Commands",
        description="All available commands",
        color=discord.Color.purple()
    )
    
    embed.add_field(
        name="/linkvp <code>",
        value="Link your Growtopia account",
        inline=False
    )
    embed.add_field(
        name="/profile",
        value="View your stats and VP balance",
        inline=False
    )
    embed.add_field(
        name="/rewards",
        value="View reward system information",
        inline=False
    )
    embed.add_field(
        name="/help",
        value="Show this message",
        inline=False
    )
    
    embed.add_field(
        name="🎮 In-Game Commands",
        value="`/linkvp` - Get link code\n"
              "`/vp` - Check and spend VP\n"
              "`/vp <amount>` - Spend VP (coming soon)",
        inline=False
    )
    
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
