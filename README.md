Metti subito DHCP + DNS (anche se non c’è internet)
1A) Usa systemd-networkd (robusto e persistente)
# 1) crea un file di rete in DHCP
sudo tee /etc/systemd/network/10-dhcp.network >/dev/null <<'EOF'
[Match]
Name=ens4

[Network]
DHCP=yes
EOF

# 2) abilita networkd
sudo systemctl enable --now systemd-networkd

# 3) (DNS) se /etc/resolv.conf manca o è un symlink rotto, riscrivilo "a mano"
sudo rm -f /etc/resolv.conf
printf "nameserver 1.1.1.1\nnameserver 8.8.8.8\n" | sudo tee /etc/resolv.conf

# 4) riapplica e verifica
sudo networkctl reload
sudo networkctl reconfigure ens4
ip -4 addr show dev ens4
ip route


Se il DHCP del tuo lab fornisce già DNS, potrai lasciare così; intanto quei due resolver funzionano ovunque.

(Alternativa rapida solo temporanea)

Se preferisci solo provarci “al volo” senza file:

sudo ip link set ens4 up
# (se presente) dhclient può assegnare DHCP temporaneo
sudo apt-get update || true
sudo apt-get -y install isc-dhcp-client || true
sudo dhclient -v ens4
printf "nameserver 1.1.1.1\n" | sudo tee /etc/resolv.conf


Ma ti consiglio networkd (1A) perché resta configurato anche ai reboot.

2) Verifica connettività
ping -c 2 1.1.1.1
getent hosts github.com
curl -I https://github.com


Se questi passano, sei online.

3) Installa git e clona il tuo repo
sudo apt-get update
sudo apt-get -y install git curl

git clone https://github.com/fraidotube/fakecam.git
cd fakecam/installer

4) Lancia l’installer dal repo

Porta HTTP a tua scelta (qui 8080):

sudo env FAKECAM_HTTP_PORT=8080 \
  MEDIAMTX_URL='https://github.com/bluenviron/mediamtx/releases/download/v1.15.1/mediamtx_v1.15.1_linux_amd64.tar.gz' \
  ./install.sh


Cosa fa:

installa pacchetti necessari (nginx, ffmpeg, python venv, htpasswd…)

scarica MediaMTX (v1.15.1)

installa NetUI, servizi systemd, sito nginx

abilita basic auth admin/admin (cambiala poi da NetUI)

abilita systemd-networkd (già fatto sopra, ma è idempotente)

5) Prova servizi
# NetUI backend
ss -ltnp | grep ':5001' || true

# MediaMTX (HLS su 8888)
curl -I http://127.0.0.1:8888/cam1/index.m3u8

# Nginx porta 8080
curl -I http://127.0.0.1:8080/


Apri dal browser:

NetUI: http://IP:8080/netui/ (user/pass: admin/admin)

Stream HLS (protetto): http://IP:8080/hls/cam1/index.m3u8
