import streamlit as st
import google.generativeai as genai
import gspread
import json
import pandas as pd
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. CONFIGURAÇÃO DA PÁGINA (SEMPRE O PRIMEIRO COMANDO) ---
st.set_page_config(page_title="Should Cost - IA", page_icon="🚛", layout="wide")

# --- 2. CREDENCIAIS E LINKS ---
CHAVE_API_GEMINI = st.secrets["GEMINI_API_KEY"]
LINK_PLANILHA = "https://docs.google.com/spreadsheets/d/1fx4Wo57AStcBe4CPlsNU7NvAQLw3rnApXJGmPwT58uI/edit?usp=sharing"

genai.configure(api_key=CHAVE_API_GEMINI)

# --- CABEÇALHO DO APLICATIVO ---
st.title("🚛 Inteligência de Fretes - Natura")
st.markdown("Assistente inteligente alimentado pelo **Google Gemini** e integrado ao seu **Google Sheets**.")
st.divider()

# --- 3. LENDO DADOS DA PLANILHA PARA ENSINAR A IA ---
@st.cache_data(ttl=600)
def ler_base_sheets():
    escopos = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    
    credenciais_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    credenciais = ServiceAccountCredentials.from_json_keyfile_dict(credenciais_dict, escopos)
    
    cliente = gspread.authorize(credenciais)
    planilha = cliente.open_by_url(LINK_PLANILHA)
    
    # Lendo as abas
    dados_ia = planilha.worksheet("Base_IA").get_all_records()
    dados_parametros = planilha.worksheet("Parametros_Custos").get_all_records()
    dados_rotas = planilha.worksheet("Rotas_Ativas").get_all_records()
    
    return {
        "contexto": str(dados_ia) + str(dados_parametros),
        "tabela_rotas": pd.DataFrame(dados_rotas)
    }

# Carregamento inicial
try:
    base_dados = ler_base_sheets()
    contexto_planilha = base_dados["contexto"]
    df_rotas_real = base_dados["tabela_rotas"]
except Exception as e:
    st.error(f"Erro ao carregar abas: {e}")
    df_rotas_real = pd.DataFrame() # Cria vazio se der erro

# Criação de duas abas na tela
aba_dashboard, aba_ia = st.tabs(["📊 Rotas Ativas", "🤖 Agente de Simulação"])

# ==========================================
# ABA 1: A PÁGINA INICIAL DAS ROTAS ATIVAS
# ==========================================
with aba_dashboard:
    st.subheader("📊 Acompanhamento de Rotas Ativas (OTM)")
    
    if not df_rotas_real.empty:
        # Selecionando e renomeando as colunas chave para a visão do Alex
        colunas_visao = {
            "NOME_TRANSPORTADORA": "Transportadora",
            "DESCRICAO_ZONA_DE_TRANSPORTE_ORIGEM": "Origem",
            "DESCRICAO_ZONA_DE_TRANSPORTE_DESTINO": "Destino",
            "DESCRICAO_GRUPO_DE_EQUIPAMENTO": "Veículo",
            "VALOR_DE_CONTRATO": "Custo Atual (R$)",
            "DATA_DE_EXPIRACAO": "Validade"
        }
        
        # Criamos um DataFrame apenas com o que queremos exibir
        df_display = df_rotas_real[list(colunas_visao.keys())].rename(columns=colunas_visao)
        
        # Filtro rápido por Transportadora
        transportadora_selecionada = st.multiselect("Filtrar por Transportadora:", options=df_display["Transportadora"].unique())
        if transportadora_selecionada:
            df_display = df_display[df_display["Transportadora"].isin(transportadora_selecionada)]

        # Exibe a tabela real do OTM
        st.dataframe(df_display, use_container_width=True, hide_index=True)

        # Botão de Download (Aqui baixamos a tabela COMPLETA com todas as colunas do OTM)
        csv = df_rotas_real.to_csv(index=False, sep=';').encode('utf-8-sig')
        st.download_button(
            label="📥 Exportar Base Completa (OTM + Custos)",
            data=csv,
            file_name="relatorio_rotas_natura.csv",
            mime="text/csv",
        )
    else:
        st.warning("Nenhuma rota encontrada na aba 'Rotas_Ativas'.")
    st.write("Visão geral das rotas atualmente monitoradas pelo sistema.")

    # Exemplo de tabela (No futuro, vamos puxar isso do Google Sheets)
    dados_exemplo = {
        "ID Rota": ["R-001", "R-002", "R-003"],
        "Origem -> Destino": ["Cajamar/SP -> Rio de Janeiro/RJ", "Benevides/PA -> Recife/PE", "Cajamar/SP -> Curitiba/PR"],
        "Veículo Padrão": ["VOLVO/FH 540", "SCANIA/R540", "DAF XF FT480"],
        "Distância (km)": [430, 2100, 400],
        "Custo Atual Estimado": ["R$ 3.200,00", "R$ 15.400,00", "R$ 2.950,00"]
    }
    df_rotas = pd.DataFrame(dados_exemplo)

    # Mostra a tabela de forma interativa na tela
    st.dataframe(df_rotas, use_container_width=True, hide_index=True)

    # O Botão Mágico de Download
    csv = df_rotas.to_csv(index=False, sep=';').encode('utf-8-sig')
    st.download_button(
        label="📥 Fazer Download (Excel/CSV)",
        data=csv,
        file_name="rotas_ativas_natura.csv",
        mime="text/csv",
    )

# ==========================================
# ABA 2: O SEU AGENTE DE IA (CHAT)
# ==========================================
with aba_ia:
    st.subheader("Simule novos cenários com o Agente")
# --- 3. CONFIGURANDO A MENTE DO GEMINI (VERSÃO COMPLETA COM ANTT) ---
    instrucao_sistema = f"""
    Você é um Engenheiro de Logística Sênior da Natura. Sua missão é calcular o 'Should Cost' e comparar com o 'Piso ANTT'.

    REGRAS DE CÁLCULO:
    
    1. CUSTO REAL (Should Cost):
       - Combustível: Valor por Estado (ANP).
       - Lubrificante: +5% sobre o Diesel.
       - Custos Fixos: IPVA (1% FIPE/12), Seguro (2.5% FIPE/12), Licenciamento e Tacógrafo.
       - Margem: Adicione 10% de lucro sobre o total.

    2. PISO MÍNIMO LEGAL (ANTT):
       - Localize na aba Apoio_ANTT o 'CCD' e o 'CC' de acordo com os eixos do veículo.
       - FÓRMULA: (Distância * CCD) + CC.
       - Se o usuário não falar a distância, pergunte ou use a distância da aba Rotas_Ativas.

    DADOS PARA CONSULTA:
    {contexto_planilha}

    COMPARAÇÃO:
    Ao final da resposta, diga se o valor de contrato da Natura (visto na aba Rotas_Ativas) está ACIMA ou ABAIXO do Piso da ANTT.
    """

    modelo = genai.GenerativeModel(
        model_name="gemini-3.1-flash-lite-preview",
        system_instruction=instrucao_sistema
    )

    # --- MEMÓRIA DO CHAT ---
    if "mensagens" not in st.session_state:
        st.session_state.mensagens = []
        st.session_state.chat_gemini = modelo.start_chat(history=[])

    # Desenha as mensagens antigas na tela
    for msg in st.session_state.mensagens:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # --- A INTERFACE DE TEXTO ---
    pergunta = st.chat_input("Pergunte ao Agente: Qual o custo estimado para 500km?")

    if pergunta:
        # Mostra pergunta do usuário
        with st.chat_message("user"):
            st.markdown(pergunta)
        st.session_state.mensagens.append({"role": "user", "content": pergunta})

        # Mostra a IA pensando e respondendo
        with st.chat_message("assistant"):
            resposta_placeholder = st.empty()
            resposta_placeholder.markdown("Consultando a planilha e calculando... ⚙️")
            
            try:
                resposta_gemini = st.session_state.chat_gemini.send_message(pergunta)
                texto_final = resposta_gemini.text
                resposta_placeholder.markdown(texto_final)
                
                # Salva na memória
                st.session_state.mensagens.append({"role": "assistant", "content": texto_final})
            except Exception as e:
                resposta_placeholder.markdown(f"**Erro na IA:** Verifique se a sua Chave de API está correta. Detalhes: {e}")