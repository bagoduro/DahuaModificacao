#!/bin/bash

# Caminho para o arquivo de configuração
config_file="/root/DahuaConsole/last_run.conf"

# Cores ANSI
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
GREEN='\033[1;32m'
RED='\033[1;31m'
NC='\033[0m' # Sem cor

# Função para ler valores do arquivo de configuração
read_config() {
    if [ -f "$config_file" ]; then
        source "$config_file"
    fi
}

# Função para salvar valores no arquivo de configuração
save_config() {
    echo "ips=\"$ips\"" > "$config_file"
    echo "portas=\"$portas\"" >> "$config_file"
}

read_config

echo -e "${GREEN}==============================${NC}"
echo -e "${GREEN}      MASSCAN LAUNCHER        ${NC}"
echo -e "${GREEN}==============================${NC}"
echo

# Entrada de IPs em múltiplas linhas
echo -e "Digite os IPs/redes/ranges ou DDNS (um por linha)"
echo -e "${BLUE}Exemplos:${NC}"
echo -e "${BLUE}192.168.0.0-192.168.10.254${NC}"
echo -e "${BLUE}192.168.0.0/12${NC}"
echo -e "${BLUE}andrecosta.ddns-intelbras.com.br${NC}"
echo
echo -e "Pressione ENTER em uma linha vazia para finalizar."
echo

if [ -n "$ips" ]; then
    echo -e "Atual:"
    echo -e "${YELLOW}$ips${NC}" | tr ' ' '\n'
    echo
fi

input_ips=""
while IFS= read -r line; do
    [ -z "$line" ] && break
    input_ips+="$line "
done

echo
echo -e "Digite as portas (${BLUE}ex: 554,37777${NC})"
echo -e "Atual [${YELLOW}${portas}${NC}]: \c"
read input_portas

ips="${input_ips:-$ips}"
portas="${input_portas:-$portas}"

# Normaliza múltiplas linhas/espaços
ips=$(echo "$ips" | tr '\n' ' ' | xargs)

if [ -z "$ips" ] || [ -z "$portas" ]; then
    echo -e "${RED}IPs ou Portas não fornecidos. Saindo.${NC}"
    exit 1
fi

# --- Validação e Resolução de DDNS/IPs ---
valid=true
ips_resolvidos=""

for item in $ips; do
    # Verifica se já é um formato válido de IP, Range ou CIDR
    if [[ $item =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}(/[0-9]{1,2}|-([0-9]{1,3}\.){3}[0-9]{1,3})?$ ]]; then
        ips_resolvidos+="$item "
    else
        # Se não for formato de IP, assume que é um DDNS/Domínio e tenta resolver
        echo -e "${BLUE}Resolvendo DDNS:${NC} $item..."
        ip_obtido=$(dig +short "$item" | tail -n1)

        # Valida se o resultado da resolução é um IP válido
        if [[ -n "$ip_obtido" && $ip_obtido =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
            echo -e "${GREEN}DDNS resolvido para:${NC} $ip_obtido"
            ips_resolvidos+="$ip_obtido "
        else
            echo -e "${RED}Erro: Não foi possível resolver ou formato inválido em:${NC} ${YELLOW}$item${NC}"
            valid=false
        fi
    fi
done

if [ "$valid" = false ]; then
    echo -e "${RED}Validação falhou. Verifique os formatos ou conexões de DDNS.${NC}"
    exit 1
fi

# Alimenta a variável ips com a lista de IPs reais convertidos
ips=$(echo "$ips_resolvidos" | xargs)

save_config

echo
echo -e "${GREEN}Alvos carregados:${NC}"
for item in $ips; do
    echo -e " - ${BLUE}$item${NC}"
done

echo

# Detecção de Interface
interface=$(ip route get 8.8.8.8 2>/dev/null | awk '{print $5; exit}')

if [ -z "$interface" ]; then
    interface=$(ip link show | grep 'state UP' | awk -F': ' '{print $2}' | head -n 1)
fi

if [ -z "$interface" ]; then
    echo -e "${RED}Não foi possível detectar interface de rede.${NC}"
    exit 1
fi

echo -e "${GREEN}Interface detectada:${NC} ${YELLOW}$interface${NC}"
echo

# Execução do Masscan
echo -e "${GREEN}Executando masscan...${NC}"
echo -e "${BLUE}Portas:${NC} $portas"
echo -e "${BLUE}Targets:${NC} $ips"
echo

sudo masscan -p "$portas" $ips --rate 22500 -oL /root/DahuaConsole/iprtsp.txt -e "$interface"

if [ $? -eq 0 ]; then
    echo
    echo -e "${GREEN}Masscan concluído com sucesso.${NC}"
else
    echo
    echo -e "${RED}Erro na execução do masscan.${NC}"
    exit 1
fi

echo

# Extração de IPs
read -p "Deseja extrair os IPs das portas 554 e 37777? (s/n): " resposta

if [[ "$resposta" =~ ^[sS]$ ]]; then

    # Porta 554 / 8554
    grep -E 'tcp (554|8554)' /root/DahuaConsole/iprtsp.txt | awk '{print $4}' > /root/DahuaConsole/ips554.txt

    # Porta 37776/37777/37778
    grep '^open tcp ' /root/DahuaConsole/iprtsp.txt | awk '{print $4 ":" $3}' > /root/DahuaConsole/ips37777.txt

    echo -e "${GREEN}IPs extraídos.${NC}"
    echo -e "Arquivo RTSP: ${YELLOW}/root/DahuaConsole/ips554.txt${NC}"
    echo -e "Arquivo Dahua: ${YELLOW}/root/DahuaConsole/ips37777.txt${NC}"
fi

original_dir=$(pwd)

while true; do

    echo
    echo -e "${GREEN}--- Menu de Ferramentas ---${NC}"
    echo "1. RTSPbrute (Porta 554)"
    echo "2. asleep_scanner (Porta 37777)"
    echo "3. Sair"
    echo

    read -p "Opção: " opcao

    case $opcao in

        1)
            cd /root/DahuaConsole/ 2>/dev/null || \
            cd /root/DahuaConsole/ 2>/dev/null

            if [ -f "/root/DahuaConsole/ips554.txt" ]; then

                echo
                echo -e "${GREEN}Executando RTSPbrute...${NC}"
                echo

                rtspbrute -t /root/DahuaConsole/ips554.txt -p 554 -st 4 -T 10

            else
                echo -e "${RED}Arquivo ips554.txt não encontrado.${NC}"
            fi

            cd "$original_dir"
            ;;

        2)
            cd /root/DahuaConsole/ || exit

            if [ -f "ips37777.txt" ]; then

                echo
                echo -e "${GREEN}Executando asleep_scanner...${NC}"
                echo

                python3 ./asleep.py -m -s /root/DahuaConsole/ips37777.txt -p 37777

            else
                echo -e "${RED}Arquivo ips37777.txt não encontrado.${NC}"
            fi

            cd "$original_dir"
            ;;

        3)
            echo -e "${GREEN}Saindo...${NC}"
            exit 0
            ;;

        *)
            echo -e "${RED}Opção inválida.${NC}"
            ;;
    esac

    echo
    read -p "Deseja executar outro programa? (s/n): " repetir

    [[ ! "$repetir" =~ ^[sS]$ ]] && break
done
