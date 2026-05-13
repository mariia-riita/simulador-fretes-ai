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
LINK_PLANILHA = "https://docs.google.com/spreadsheets/d/12TSlwkvaklIWr4NBkAeM11vSfj9K_ycFZzqyGW9ImX0/edit?usp=sharing"

genai.configure(api_key=CHAVE_API_GEMINI)

# --- CABEÇALHO DO APLICATIVO ---
st.title("🚛 Inteligência de Fretes - Natura")
st.markdown("Assistente inteligente alimentado pelo **Google Gemini** e integrado ao seu **Google Sheets**.")
st.divider()

# --- 3. LENDO DADOS DA PLANILHA PARA ENSINAR A IA ---
@st.cache_data(ttl=600)
def ler_base_sheets():
    escopos = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    
    # Lemos o JSON direto do Cofre
    credenciais_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    credenciais = ServiceAccountCredentials.from_json_keyfile_dict(credenciais_dict, escopos)
    
    cliente = gspread.authorize(credenciais)
    planilha = cliente.open_by_url(LINK_PLANILHA)
    
    # Lendo as abas ATUALIZADAS (agora com as 5 abas corretas)
    dados_anp = planilha.worksheet("Apoio_ANP").get_all_records()
    dados_fipe = planilha.worksheet("Apoio_FIPE").get_all_records()
    dados_antt = planilha.worksheet("Apoio_ANTT").get_all_records()
    dados_parametros = planilha.worksheet("Parametros_Custos").get_all_records()
    dados_rotas = planilha.worksheet("Rotas_Ativas").get_all_records()
    
    # Juntando tudo na "Memória" da IA
    contexto_ia = f"ANP: {dados_anp}\nFIPE: {dados_fipe}\nANTT: {dados_antt}\nPARAMETROS: {dados_parametros}"
    
    return {
        "contexto": contexto_ia,
        "tabela_rotas": pd.DataFrame(dados_rotas)
    }

# Carregamento inicial com Trava de Segurança
try:
    base_dados = ler_base_sheets()
    contexto_planilha = base_dados["contexto"]
    df_rotas_real = base_dados["tabela_rotas"]
except Exception as e:
    st.error(f"Erro de conexão com o Google Sheets: {e}")
    df_rotas_real = pd.DataFrame() # Cria tabela vazia pra não quebrar a tela
    contexto_planilha = "Dados temporariamente indisponíveis. Responda que não foi possível conectar à base." # Evita o NameError!
# Criação de duas abas na tela
aba_dashboard, aba_ia = st.tabs(["📊 Rotas Ativas", "🤖 Agente de Simulação"])

# ==========================================
# ABA 1: A PÁGINA INICIAL DAS ROTAS ATIVAS
# ==========================================
with aba_dashboard:
    st.subheader("📊 Acompanhamento de Rotas Ativas (OTM)")
    
    if not df_rotas_real.empty:
        # 1. Remove espaços invisíveis de todos os cabeçalhos
        df_rotas_real.columns = df_rotas_real.columns.str.strip()
        
        # --- MÁQUINA DE LIMPEZA FINANCEIRA ---
        # Função para garantir que os valores virem números (mesmo que venham com R$, vírgulas ou vazios)
        def limpar_moeda(coluna):
            if pd.api.types.is_numeric_dtype(coluna):
                return coluna.fillna(0)
            return pd.to_numeric(
                coluna.astype(str)
                .str.replace(r'[R\$\s]', '', regex=True) # Tira o R$ e espaços
                .str.replace(r'\.', '', regex=True)     # Tira o ponto de milhar
                .str.replace(',', '.', regex=True),     # Troca a vírgula por ponto
                errors='coerce'
            ).fillna(0)

        # 2. Puxa as colunas reais e cria a coluna somada se elas existirem
        custo_base = limpar_moeda(df_rotas_real.get("CUSTO_BASE", pd.Series([0]*len(df_rotas_real))))
        pedagio = limpar_moeda(df_rotas_real.get("PEDAGIO", pd.Series([0]*len(df_rotas_real))))
        
        # A MÁGICA DA SOMA AQUI:
        df_rotas_real["CUSTO_CALCULADO"] = custo_base + pedagio
        
        # Formata o resultado para o padrão visual R$ 0.000,00
        df_rotas_real["Custo Atual (R$)"] = df_rotas_real["CUSTO_CALCULADO"].apply(
            lambda x: f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        )
        
        # 3. Selecionando e renomeando as colunas chave
        colunas_visao = {
            "NOME_TRANSPORTADORA": "Transportadora",
            "DESCRICAO_ZONA_DE_TRANSPORTE_ORIGEM": "Origem",
            "DESCRICAO_ZONA_DE_TRANSPORTE_DESTINO": "Destino",
            "DESCRICAO_GRUPO_DE_EQUIPAMENTO": "Veículo",
            "Custo Atual (R$)": "Custo Atual (R$)", # Agora puxamos a coluna que nós mesmos criamos!
            "DATA_DE_EXPIRACAO": "Validade"
        }
        
        # Filtra só as colunas que realmente existem para não dar erro
        colunas_existentes = {k: v for k, v in colunas_visao.items() if k in df_rotas_real.columns}
        df_display = df_rotas_real[list(colunas_existentes.keys())].rename(columns=colunas_existentes)
        
        st.markdown("### 🎯 Resumo da Operação")
        
        col1, col2, col3, col4 = st.columns(4)
        
        qtd_rotas = len(df_display)
        qtd_transportadoras = df_display["Transportadora"].nunique() if "Transportadora" in df_display.columns else 0
        qtd_origens = df_display["Origem"].nunique() if "Origem" in df_display.columns else 0
        
        # Novo KPI Financeiro: Custo Médio por Viagem da Operação Inteira
        custo_medio = df_rotas_real["CUSTO_CALCULADO"].mean()
        custo_medio_formatado = f"R$ {custo_medio:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        
        col1.metric("Total de Rotas Ativas", qtd_rotas)
        col2.metric("Transportadoras", qtd_transportadoras)
        col3.metric("Zonas de Origem", qtd_origens)
        col4.metric("Custo Médio da Base", custo_medio_formatado) # Adicionei o KPI financeiro no último cartão!
        
        st.divider()

        # 4. Filtro rápido por Transportadora
        if "Transportadora" in df_display.columns:
            transportadora_selecionada = st.multiselect("Filtrar por Transportadora:", options=df_display["Transportadora"].unique())
            if transportadora_selecionada:
                df_display = df_display[df_display["Transportadora"].isin(transportadora_selecionada)]

        # 5. Exibe a tabela na tela
        st.dataframe(df_display, use_container_width=True, hide_index=True)

        # 6. Botão de Download (Baixa a base completa do OTM + Nossa coluna calculada)
        csv = df_rotas_real.to_csv(index=False, sep=';').encode('utf-8-sig')
        st.download_button(
            label="📥 Exportar Base Completa (OTM + Custos)",
            data=csv,
            file_name="relatorio_rotas_natura.csv",
            mime="text/csv",
        )
    else:
        st.warning("Nenhuma rota encontrada na aba 'Rotas_Ativas'.")
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
