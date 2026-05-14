import streamlit as st
import google.generativeai as genai
import gspread
import pandas as pd
from oauth2client.service_account import ServiceAccountCredentials
import json
import requests
import time
from io import BytesIO

# --- 1. CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Should Cost IA - Natura", page_icon="🚛", layout="wide")

# --- 2. CONSTANTES E SEGURANÇA ---
CHAVE_API_GEMINI = st.secrets["GEMINI_API_KEY"]
LINK_PLANILHA = "https://docs.google.com/spreadsheets/d/12TSlwkvaklIWr4NBkAeM11vSfj9K_ycFZzqyGW9ImX0/edit?usp=sharing"

genai.configure(api_key=CHAVE_API_GEMINI)

# Dicionário Geográfico para a ANP
mapa_estados = {
    'ACRE': ['AC', 'Rio Branco', 'Norte'], 'ALAGOAS': ['AL', 'Maceió', 'Nordeste'],
    'AMAPA': ['AP', 'Macapá', 'Norte'], 'AMAZONAS': ['AM', 'Manaus', 'Norte'],
    'BAHIA': ['BA', 'Salvador', 'Nordeste'], 'CEARA': ['CE', 'Fortaleza', 'Nordeste'],
    'DISTRITO FEDERAL': ['DF', 'Brasília', 'Centro-Oeste'], 'ESPIRITO SANTO': ['ES', 'Vitória', 'Sudeste'],
    'GOIAS': ['GO', 'Goiânia', 'Centro-Oeste'], 'MARANHAO': ['MA', 'São Luís', 'Nordeste'],
    'MATO GROSSO': ['MT', 'Cuiabá', 'Centro-Oeste'], 'MATO GROSSO DO SUL': ['MS', 'Campo Grande', 'Centro-Oeste'],
    'MINAS GERAIS': ['MG', 'Belo Horizonte', 'Sudeste'], 'PARA': ['PA', 'Belém', 'Norte'],
    'PARAIBA': ['PB', 'João Pessoa', 'Nordeste'], 'PERNAMBUCO': ['PE', 'Recife', 'Nordeste'],
    'PIAUI': ['PI', 'Teresina', 'Nordeste'], 'PARANA': ['PR', 'Curitiba', 'Sul'],
    'RIO DE JANEIRO': ['RJ', 'Rio de Janeiro', 'Sudeste'], 'RIO GRANDE DO NORTE': ['RN', 'Natal', 'Nordeste'],
    'RIO GRANDE DO SUL': ['RS', 'Porto Alegre', 'Sul'], 'RONDONIA': ['RO', 'Porto Velho', 'Norte'],
    'RORAIMA': ['RR', 'Boa Vista', 'Norte'], 'SANTA CATARINA': ['SC', 'Florianópolis', 'Sul'],
    'SAO PAULO': ['SP', 'São Paulo', 'Sudeste'], 'SERGIPE': ['SE', 'Aracaju', 'Nordeste'],
    'TOCANTINS': ['TO', 'Palmas', 'Norte']
}

# --- 3. FUNÇÕES DO MOTOR DE AUTOMAÇÃO (OPÇÃO 2 - NUVEM) ---

def limpar_moeda(coluna):
    """Converte strings de moeda (R$ 1.200,00) para números flutuantes"""
    if pd.api.types.is_numeric_dtype(coluna):
        return coluna.fillna(0)
    return pd.to_numeric(
        coluna.astype(str)
        .str.replace(r'[R\$\s]', '', regex=True)
        .str.replace(r'\.', '', regex=True)
        .str.replace(',', '.', regex=True),
        errors='coerce'
    ).fillna(0)

def formatar_brl(valor):
    """Formata número para string R$ 1.234,56"""
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# --- ANP ---
    url_anp = "https://www.gov.br/anp/pt-br/assuntos/precos-e-custos-operacionais/precos-revenda-e-de-distribuicao-de-combustiveis/shlp/semanal/semanal-estados-desde-2013.xlsx"
    
    # 1. Colocamos uma "máscara" no robô para o governo não bloquear
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    resp = requests.get(url_anp, headers=headers, verify=False, timeout=20)
    
    # 2. Trava de Segurança: Verifica se o arquivo é um Excel mesmo ou se o governo deu erro
    if resp.status_code != 200 or b"<html" in resp.content[:500].lower():
        st.error("⚠️ O site do Governo (ANP) bloqueou o download ou o link da planilha mudou. Tente novamente mais tarde.")
        return False
        
    # 3. Lê o Excel em segurança
    df_anp_raw = pd.read_excel(BytesIO(resp.content), skiprows=9)
    df_anp_raw.columns = df_anp_raw.columns.astype(str).str.strip().str.upper()
    # --- FIPE ---
    frota = {"VOLVO/FH 540": "516213-0", "DAF XF FT480": "530014-2", "VOLVO/FH 460": "516171-1", "SCANIA/R540": "513308-4"}
    dados_fipe = []
    for mod, cod in frota.items():
        try:
            r = requests.get(f"https://fipe.parallelum.com.br/api/v2/trucks/{cod}/years", timeout=10).json()
            p = requests.get(f"https://fipe.parallelum.com.br/api/v2/trucks/{cod}/years/{r[0]['code']}", timeout=10).json()
            dados_fipe.append([mod, p['price']])
        except: dados_fipe.append([mod, "Erro"])
    df_fipe = pd.DataFrame(dados_fipe, columns=['Modelo Veículo', 'Preço Veículo'])

    # --- ANTT ---
    dados_antt = [
        ['Carga Geral', 2, 4.0031, 436.39], ['Carga Geral', 3, 5.1295, 523.33],
        ['Carga Geral', 4, 5.8178, 568.72], ['Carga Geral', 5, 6.7126, 635.08],
        ['Carga Geral', 6, 7.4124, 648.95], ['Carga Geral', 7, 8.1252, 803.22],
        ['Carga Geral', 9, 9.2466, 872.44]
    ]
    df_antt = pd.DataFrame(dados_antt, columns=['Tipo de Carga', 'Eixos', 'CCD (R$/km)', 'CC (R$/viagem)'])

    # Salvar no Sheets
    for nome, df in [("Apoio_ANP", df_anp_final), ("Apoio_FIPE", df_fipe), ("Apoio_ANTT", df_antt)]:
        aba = planilha.worksheet(nome)
        aba.clear()
        aba.update([df.columns.values.tolist()] + df.values.tolist())
    
    return True

# --- 4. CARREGAMENTO DE DADOS (CACHE) ---
@st.cache_data(ttl=600)
def ler_base_sheets():
    escopos = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    cred_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    credenciais = ServiceAccountCredentials.from_json_keyfile_dict(cred_dict, escopos)
    cliente = gspread.authorize(credenciais)
    planilha = cliente.open_by_url(LINK_PLANILHA)
    
    anp = planilha.worksheet("Apoio_ANP").get_all_records()
    fipe = planilha.worksheet("Apoio_FIPE").get_all_records()
    antt = planilha.worksheet("Apoio_ANTT").get_all_records()
    param = planilha.worksheet("Parametros_Custos").get_all_records()
    rotas = planilha.worksheet("Rotas_Ativas").get_all_records()
    
    contexto = f"ANP: {anp}\nFIPE: {fipe}\nANTT: {antt}\nPARAMETROS: {param}"
    return {"contexto": contexto, "tabela": pd.DataFrame(rotas)}

# --- 5. INTERFACE DO USUÁRIO ---
st.title("🚛 Inteligência de Fretes - Natura")

# Sidebar com Botão de Sincronização
with st.sidebar:
    st.header("⚙️ Controle")
    st.markdown("Clique abaixo se a planilha base foi atualizada recentemente.")
    
    # O botão agora apenas limpa o cache e puxa os dados fresquinhos do Sheets
    if st.button("🔄 Atualizar Painel de Dados"):
        with st.spinner("Buscando dados mais recentes da planilha..."):
            st.cache_data.clear() # A mágica que apaga a memória antiga
            st.success("Painel atualizado com sucesso!")
            time.sleep(1)
            st.rerun()

# Carregamento Inicial
try:
    dados_carregados = ler_base_sheets()
    contexto_ia = dados_carregados["contexto"]
    df_rotas = dados_carregados["tabela"]
except Exception as e:
    st.error(f"Erro ao conectar: {e}")
    df_rotas = pd.DataFrame()
    contexto_ia = ""

aba_dash, aba_ia = st.tabs(["📊 Rotas Ativas (OTM)", "🤖 Agente de Simulação"])

with aba_dash:
    if not df_rotas.empty:
        df_rotas.columns = df_rotas.columns.str.strip()
        base = limpar_moeda(df_rotas.get("CUSTO_BASE", pd.Series([0]*len(df_rotas))))
        pedagio = limpar_moeda(df_rotas.get("PEDAGIO", pd.Series([0]*len(df_rotas))))
        df_rotas["CUSTO_TOTAL"] = base + pedagio
        
        # KPIs
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Rotas Ativas", len(df_rotas))
        col2.metric("Transportadoras", df_rotas["NOME_TRANSPORTADORA"].nunique() if "NOME_TRANSPORTADORA" in df_rotas.columns else 0)
        col3.metric("Custo Médio", formatar_brl(df_rotas["CUSTO_TOTAL"].mean()))
        col4.metric("Total Fretes", formatar_brl(df_rotas["CUSTO_TOTAL"].sum()))

        # Tabela
        df_view = df_rotas.copy()
        df_view["Custo Atual"] = df_view["CUSTO_TOTAL"].apply(formatar_brl)
        st.dataframe(df_view[["NOME_TRANSPORTADORA", "DESCRICAO_ZONA_DE_TRANSPORTE_ORIGEM", "DESCRICAO_ZONA_DE_TRANSPORTE_DESTINO", "Custo Atual"]], use_container_width=True)
    else:
        st.info("Aba Rotas_Ativas vazia ou inacessível.")

with aba_ia:
    instrucao = f"""Você é um Engenheiro de Logística Sênior da Natura. Calcule o 'Should Cost' e compare com o 'Piso ANTT'.
    REGRAS: 1. Custo Real: Diesel (ANP) + 5% Lubrificante + Fixos (IPVA 1% FIPE/12, Seguro 2.5%/12) + 10% Margem.
    2. ANTT: (Distância * CCD) + CC da aba Apoio_ANTT.
    DADOS: {contexto_ia}"""
    
    if "chat" not in st.session_state:
        st.session_state.chat = genai.GenerativeModel("gemini-3.1-flash-lite-preview", system_instruction=instrucao).start_chat(history=[])
        st.session_state.msgs = []

    for m in st.session_state.msgs:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    pergunta = st.chat_input("Ex: Qual o custo de Cajamar para Recife?")
    if pergunta:
        st.chat_message("user").markdown(pergunta)
        st.session_state.msgs.append({"role": "user", "content": pergunta})
        with st.chat_message("assistant"):
            try:
                res = st.session_state.chat.send_message(pergunta).text
                st.markdown(res)
                st.session_state.msgs.append({"role": "assistant", "content": res})
            except Exception as e: st.error(f"Erro na IA: {e}")
