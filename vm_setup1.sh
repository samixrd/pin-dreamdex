#!/usr/bin/env bash
set -e
cd ~/pin
# ssh: github via deploy key
grep -q "github.com" ~/.ssh/config 2>/dev/null || cat >> ~/.ssh/config <<'EOF'
Host github.com
  HostName github.com
  User git
  IdentityFile ~/.ssh/id_deploy
  IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config
git config user.email "pin@vm" && git config user.name "pin-vm"
git remote set-url origin git@github.com:samixrd/pin-dreamdex.git 2>/dev/null || git remote add origin git@github.com:samixrd/pin-dreamdex.git
ssh -o StrictHostKeyChecking=accept-new -T git@github.com 2>&1 | head -1 || true
# pages publish helper (VM -> repo docs/)
cat > publish_pages.sh <<'EOS'
#!/usr/bin/env bash
cd ~/pin
python3 dashboard.py >/dev/null 2>&1 || true
cp data/dashboard.html docs/index.html
if ! git diff --quiet docs/index.html; then
  git add docs/index.html && git commit -qm "pages: vm auto $(date -u +%H:%M)" && git push -q origin main
fi
EOS
chmod +x publish_pages.sh
# crontab: tick (rail refresh + publish) + pages every 15m
(crontab -l 2>/dev/null; echo "*/15 * * * * $HOME/pin/publish_pages.sh >> $HOME/pin/data/pages.log 2>&1") | sort -u | crontab -
crontab -l | tail -2
