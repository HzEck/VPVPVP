#!/bin/bash

echo "======================================"
echo "  DISCORD VOICE REWARDS BOT - SETUP  "
echo "======================================"
echo ""

# Renk kodları
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Bu script seni adım adım kurulum boyunca yönlendirecek.${NC}"
echo ""

# 1. Discord Token
echo -e "${GREEN}[1/4]${NC} Discord Bot Token"
echo "Discord Developer Portal'dan bot token'ını aldın mı?"
echo -e "${YELLOW}https://discord.com/developers/applications${NC}"
read -p "Bot Token'ını gir: " DISCORD_TOKEN

if [ -z "$DISCORD_TOKEN" ]; then
    echo -e "${RED}Token gerekli!${NC}"
    exit 1
fi

# 2. API URL
echo ""
echo -e "${GREEN}[2/4]${NC} Growtopia Sunucu API URL"
read -p "API Base URL (örn: https://server.com/casino): " API_URL

if [ -z "$API_URL" ]; then
    echo -e "${RED}API URL gerekli!${NC}"
    exit 1
fi

# 3. VP Channel ID
echo ""
echo -e "${GREEN}[3/4]${NC} VP Kazanma Kanalı"
echo "Discord'da ses kanalına sağ tıkla > Copy Channel ID"
read -p "VP Channel ID: " VP_CHANNEL

if [ -z "$VP_CHANNEL" ]; then
    echo -e "${RED}VP Channel ID gerekli!${NC}"
    exit 1
fi

# 4. Gems Channel ID
echo ""
echo -e "${GREEN}[4/4]${NC} Gems Boost Kanalı"
read -p "Gems Channel ID: " GEMS_CHANNEL

if [ -z "$GEMS_CHANNEL" ]; then
    echo -e "${RED}Gems Channel ID gerekli!${NC}"
    exit 1
fi

# .env dosyası oluştur
echo ""
echo -e "${YELLOW}Environment dosyası oluşturuluyor...${NC}"

cat > .env << EOF
DISCORD_TOKEN=${DISCORD_TOKEN}
API_BASE_URL=${API_URL}
VP_CHANNEL_ID=${VP_CHANNEL}
GEMS_CHANNEL_ID=${GEMS_CHANNEL}
EOF

echo -e "${GREEN}✓ .env dosyası oluşturuldu!${NC}"

# Test çalıştırma
echo ""
echo -e "${YELLOW}Botu test etmek ister misin? (y/n)${NC}"
read -p "> " TEST_RUN

if [ "$TEST_RUN" = "y" ] || [ "$TEST_RUN" = "Y" ]; then
    echo ""
    echo -e "${GREEN}Bot başlatılıyor...${NC}"
    echo -e "${YELLOW}CTRL+C ile durdurabilirsin${NC}"
    echo ""
    
    # Virtual environment oluştur
    python3 -m venv venv
    source venv/bin/activate
    
    # Dependencies yükle
    pip install -r requirements.txt
    
    # Botu çalıştır
    python discord_bot.py
else
    echo ""
    echo -e "${GREEN}✓ Kurulum tamamlandı!${NC}"
    echo ""
    echo "Botu çalıştırmak için:"
    echo -e "${YELLOW}  python discord_bot.py${NC}"
    echo ""
    echo "Render'a deploy etmek için:"
    echo -e "${YELLOW}  1. GitHub'a yükle${NC}"
    echo -e "${YELLOW}  2. Render'da Web Service oluştur${NC}"
    echo -e "${YELLOW}  3. Environment variables ekle${NC}"
    echo ""
fi
