import streamlit as st
import google.generativeai as genai
import gspread
import pandas as pd
from oauth2client.service_account import ServiceAccountCredentials
import json
import time
from datetime import datetime
import pydeck as pdk

# --- 1. CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Should Cost IA - Natura", page_icon="🚛", layout="wide")

# --- 2. CONSTANTES E SEGURANÇA ---
CHAVE_API_GEMINI = st.secrets["GEMINI_API_KEY"]
LINK_PLANILHA = "https://docs.google.com/spreadsheets/d/12TSlwkvaklIWr4NBkAeM11vSfj9K_ycFZzqyGW9ImX0/edit?usp=sharing"

genai.configure(api_key=CHAVE_API_GEMINI)

# --- 3. FUNÇÕES AUXILIARES E DE BANCO DE DADOS ---
def limpar_moeda(coluna):
    """Converte strings de moeda ou números sujos para float puro"""
    if pd.api.types.is_numeric_dtype(coluna):
        return coluna.fillna(0)
    return pd.to_numeric(
        coluna.astype(str)
        .str.replace(r'[R\$\s]', '', regex=True)
        .str.replace(r'\.', '', regex=True)
        .str.replace(',', '.', regex=True),
        errors='coerce'
    ).fillna(0)

def formatar_kpi_brl(valor):
    """Formata números gigantes para milhares (mil), milhões (Mi) ou bilhões (Bi)"""
    if pd.isna(valor) or valor == 0: return "R$ 0,00"
    if valor >= 1_000_000_000: return f"R$ {valor / 1_000_000_000:.2f} Bi".replace(".", ",")
    elif valor >= 1_000_000: return f"R$ {valor / 1_000_000:.2f} Mi".replace(".", ",")
    elif valor >= 1_000: return f"R$ {valor / 1_000:.2f} mil".replace(".", ",")
    else: return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def limpar_coordenada(coord):
    """Converte coordenadas com vírgula para padrão de mapas (ponto)"""
    if pd.isna(coord) or coord == "": return None
    try:
        return float(str(coord).replace('"', '').replace(',', '.'))
    except:
        return None

def salvar_historico_ia(pergunta, resposta):
    """Grava as perguntas e simulações do Agente em uma aba de Histórico"""
    try:
        escopos = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        cred_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
        credenciais = ServiceAccountCredentials.from_json_keyfile_dict(cred_dict, escopos)
        cliente = gspread.authorize(credenciais)
        planilha = cliente.open_by_url(LINK_PLANILHA)
        
        try:
            aba_hist = planilha.worksheet("Historico_Simulacoes")
        except:
            aba_hist = planilha.add_worksheet(title="Historico_Simulacoes", rows="1000", cols="3")
            aba_hist.append_row(["Data/Hora", "Pergunta do Usuário", "Resposta do Agente IA"])
            
        data_atual = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        aba_hist.append_row([data_atual, pergunta, resposta])
    except Exception as e:
        print(f"Erro ao salvar histórico: {e}")

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

# Sidebar
with st.sidebar:
    st.header("⚙️ Controle")
    st.markdown("Clique abaixo se a planilha base foi atualizada recentemente.")
    if st.button("🔄 Atualizar Painel de Dados"):
        with st.spinner("Buscando dados mais recentes da planilha..."):
            st.cache_data.clear()
            st.success("Painel atualizado com sucesso!")
            time.sleep(1)
            st.rerun()

# Carregando Dados
try:
    dados_carregados = ler_base_sheets()
    contexto_ia = dados_carregados["contexto"]
    df_rotas = dados_carregados["tabela"]
except Exception as e:
    st.error(f"Erro ao conectar: {e}")
    df_rotas = pd.DataFrame()
    contexto_ia = ""

if not df_rotas.empty:
    df_rotas.columns = df_rotas.columns.str.strip()
    
    # --- PROCESSAMENTO FINANCEIRO E PONDERADO ---
    base = limpar_moeda(df_rotas.get("CUSTO_BASE", pd.Series([0]*len(df_rotas))))
    pedagio = limpar_moeda(df_rotas.get("PEDAGIO", pd.Series([0]*len(df_rotas))))
    volume = limpar_moeda(df_rotas.get("Vol", pd.Series([1]*len(df_rotas)))).replace(0, 1) 
    
    df_rotas["CUSTO_TOTAL"] = base + pedagio
    df_rotas["Custo_Total_Ponderado"] = df_rotas["CUSTO_TOTAL"] * volume
    
    # Cálculo do Frete Mínimo
    kms = limpar_moeda(df_rotas.get("KM's Conferidos", pd.Series([0]*len(df_rotas))))
    r_km = limpar_moeda(df_rotas.get("R$/KM", pd.Series([0]*len(df_rotas))))
    cc = limpar_moeda(df_rotas.get("CC", pd.Series([0]*len(df_rotas))))
    df_rotas["FRETE_MINIMO_CALC"] = (kms * r_km) + cc

    # --- KPIs NO TOPO ---
    st.markdown("### 🎯 Resumo da Operação (Ponderado por Volume)")
    col1, col2, col3, col4 = st.columns(4)
    
    total_rotas = len(df_rotas)
    total_volume = volume.sum()
    total_fretes = df_rotas["Custo_Total_Ponderado"].sum()
    custo_medio_real = total_fretes / total_volume if total_volume > 0 else 0
    
    col1.metric("Rotas Ativas", total_rotas)
    col2.metric("Volume Total", f"{total_volume:,.0f}".replace(",", "."))
    col3.metric("Custo Médio Real", formatar_kpi_brl(custo_medio_real))
    col4.metric("Despesa Estimada", formatar_kpi_brl(total_fretes))

    st.divider()

    # --- LAYOUT LADO A LADO ---
    col_grafico, col_chat = st.columns([1.2, 1])

    with col_grafico:
            aba_barras, aba_mapa = st.tabs(["📊 Custo por CD", "🗺️ Mapa Operacional"])
            
            with aba_barras:
                if "DESCRICAO_ZONA_DE_TRANSPORTE_ORIGEM" in df_rotas.columns:
                    df_chart = df_rotas.groupby("DESCRICAO_ZONA_DE_TRANSPORTE_ORIGEM")["Custo_Total_Ponderado"].sum().reset_index()
                    df_chart = df_chart.rename(columns={"DESCRICAO_ZONA_DE_TRANSPORTE_ORIGEM": "CD de Origem", "Custo_Total_Ponderado": "Custo R$"})
                    st.bar_chart(df_chart.set_index("CD de Origem"), use_container_width=True)
                else:
                    st.info("Coluna de Origem não encontrada.")

            with aba_mapa:
                # RADAR DE COORDENADAS: Procura as colunas ignorando espaços e letras maiúsculas/minúsculas
                col_lat_o = next((c for c in df_rotas.columns if 'LATITUDE ORIGEM' in str(c).upper()), None)
                col_lon_o = next((c for c in df_rotas.columns if 'LONGITUDE ORIGEM' in str(c).upper()), None)
                col_lat_d = next((c for c in df_rotas.columns if 'LATITUDE DESTINO' in str(c).upper()), None)
                col_lon_d = next((c for c in df_rotas.columns if 'LONGITUDE DESTINO' in str(c).upper()), None)
                
                # Se achou as 4 colunas necessárias, tenta desenhar o mapa
                if col_lat_o and col_lon_o and col_lat_d and col_lon_d:
                    df_rotas['lat_origem'] = df_rotas[col_lat_o].apply(limpar_coordenada)
                    df_rotas['lon_origem'] = df_rotas[col_lon_o].apply(limpar_coordenada)
                    df_rotas['lat_destino'] = df_rotas[col_lat_d].apply(limpar_coordenada)
                    df_rotas['lon_destino'] = df_rotas[col_lon_d].apply(limpar_coordenada)
                    
                    df_mapa = df_rotas.dropna(subset=['lat_origem', 'lon_origem', 'lat_destino', 'lon_destino'])
                    
                    if not df_mapa.empty:
                        camada_arcos = pdk.Layer(
                            "ArcLayer",
                            data=df_mapa,
                            get_source_position=["lon_origem", "lat_origem"],
                            get_target_position=["lon_destino", "lat_destino"],
                            get_source_color=[255, 140, 0, 160], # Laranja
                            get_target_color=[0, 200, 255, 160], # Azul
                            get_width=3,
                            pickable=True,
                        )
                        visao_inicial = pdk.ViewState(latitude=-15.78, longitude=-47.92, zoom=3.5, pitch=45)
                        st.pydeck_chart(pdk.Deck(layers=[camada_arcos], initial_view_state=visao_inicial, map_style="mapbox://styles/mapbox/dark-v10"))
                    else:
                        st.warning("⚠️ Encontrei as colunas, mas os números parecem estar vazios ou inválidos.")
                else:
                    # SE FALHAR, MOSTRA O NOME EXATO DAS COLUNAS PARA NÓS DESCOBRIRMOS O ERRO!
                    st.error("⚠️ Colunas de Latitude/Longitude não encontradas!")
                    st.info(f"Colunas que o robô está vendo agora: {', '.join(df_rotas.columns)}")

            with col_chat:
                st.subheader("🤖 Agente Especialista & Gerador de Dados")
                
                # --- INSTRUÇÃO ATUALIZADA: ENSINANDO A IA A CRIAR BASES DE DADOS ---
                instrucao = f"""Você é um Engenheiro de Logística Sênior da Natura e um Gerador de Dados.
                REGRAS DE CÁLCULO: 1. Custo Real: Diesel (ANP) + 5% Lubrificante + Fixos (IPVA 1% FIPE/12, Seguro 2.5%/12) + 10% Margem.
                2. ANTT: (Distância * CCD) + CC da aba Apoio_ANTT.
                
                REGRA DE OURO (CRIAR BASE DE DADOS): 
                Se o usuário pedir para 'criar uma base de dados', 'gerar tabela' ou 'simular várias rotas', você DEVE obrigatoriamente formatar sua resposta final como uma Tabela em Markdown puro (separada por barras verticais |). 
                Inclua colunas claras como: Origem, Destino, Distância (km), Veículo, Eixos, Custo Combustível, Frete Mínimo ANTT e Should Cost.
                
                DADOS DE CONSULTA: {contexto_ia}"""
                
                if "chat" not in st.session_state:
                    st.session_state.chat = genai.GenerativeModel("gemini-3.1-flash-lite-preview", system_instruction=instrucao).start_chat(history=[])
                    st.session_state.msgs = []

                # Mostra o histórico do chat
                for m in st.session_state.msgs:
                    with st.chat_message(m["role"]): st.markdown(m["content"])

                pergunta = st.chat_input("Ex: Crie uma base de dados simulando 3 rotas para o Nordeste...")
                if pergunta:
                    st.chat_message("user").markdown(pergunta)
                    st.session_state.msgs.append({"role": "user", "content": pergunta})
                    
                    with st.chat_message("assistant"):
                        try:
                            with st.spinner("Processando e gerando dados..."):
                                res = st.session_state.chat.send_message(pergunta).text
                            
                            st.markdown(res)
                            st.session_state.msgs.append({"role": "assistant", "content": res})
                            
                            # Salva no histórico do Sheets
                            salvar_historico_ia(pergunta, res)
                            
                            # --- O ESPIONADOR DE TABELAS (CONVERSOR PARA CSV) ---
                            # Se o Python achar uma tabela Markdown na resposta da IA, ele cria um CSV para download
                            if "|" in res and "---" in res:
                                linhas = res.split('\n')
                                linhas_tabela = [l.strip() for l in linhas if '|' in l]
                                
                                if len(linhas_tabela) > 2:
                                    csv_str = ""
                                    for linha in linhas_tabela:
                                        if '---' in linha: continue # Pula a linha separadora do Markdown
                                        # Limpa as barras e monta o formato CSV com ponto e vírgula
                                        linha_limpa = linha.strip().strip('|')
                                        colunas = [col.strip() for col in linha_limpa.split('|')]
                                        csv_str += ";".join(colunas) + "\n"
                                    
                                    st.success("✨ Base de dados detectada! Você pode baixá-la abaixo:")
                                    st.download_button(
                                        label="📥 Baixar Base de Dados (CSV)",
                                        data=csv_str.encode('utf-8-sig'),
                                        file_name="base_simulacao_ia.csv",
                                        mime="text/csv"
                                    )
                                    
                        except Exception as e: 
                            st.error(f"Erro na IA: {e}")
else:
    st.info("Aba Rotas_Ativas vazia ou inacessível.")
