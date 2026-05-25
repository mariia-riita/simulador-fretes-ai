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

# --- 3. MÁQUINAS DE LIMPEZA DE DADOS (À PROVA DE BALAS) ---
def limpar_numero_br(valor):
    """Converte valores financeiros para float, lidando com formatações malucas"""
    if pd.isna(valor): return 0.0
    v_str = str(valor).strip().upper()
    if v_str in ['', 'NAN', 'NULL', 'NONE']: return 0.0
    
    v_str = v_str.replace('R$', '').replace('$', '').replace(' ', '').replace('"', '')
    if '.' in v_str and ',' in v_str:
        v_str = v_str.replace('.', '').replace(',', '.')
    elif ',' in v_str:
        v_str = v_str.replace(',', '.')
        
    try:
        return float(v_str)
    except:
        return 0.0

def limpar_coordenada(coord):
    """Recupera coordenadas mesmo se o Excel tiver engolido a vírgula"""
    if pd.isna(coord): return None
    c_str = str(coord).strip().replace('"', '').replace(' ', '')
    if not c_str or c_str.upper() in ['NAN', 'NULL', 'NONE']: return None
    
    if '.' in c_str and ',' in c_str:
        c_str = c_str.replace('.', '').replace(',', '.')
    elif ',' in c_str:
        c_str = c_str.replace(',', '.')
        
    try:
        val = float(c_str)
        if val == 0.0: return None
        
        # O Salva-vidas: Se o número for gigante (ex: -2330817), devolve a vírgula pro lugar certo!
        while abs(val) > 180:
            val = val / 10.0
            
        return val
    except:
        return None

def formatar_kpi_brl(valor):
    if pd.isna(valor) or valor == 0: return "R$ 0,00"
    if valor >= 1_000_000_000: return f"R$ {valor / 1_000_000_000:.2f} Bi".replace(".", ",")
    elif valor >= 1_000_000: return f"R$ {valor / 1_000_000:.2f} Mi".replace(".", ",")
    elif valor >= 1_000: return f"R$ {valor / 1_000:.2f} mil".replace(".", ",")
    else: return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def salvar_historico_ia(pergunta, resposta):
    try:
        escopos = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        cred_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
        credenciais = ServiceAccountCredentials.from_json_keyfile_dict(cred_dict, escopos)
        cliente = gspread.authorize(credenciais)
        planilha = cliente.open_by_url(LINK_PLANILHA)
        
        try: aba_hist = planilha.worksheet("Historico_Simulacoes")
        except:
            aba_hist = planilha.add_worksheet(title="Historico_Simulacoes", rows="1000", cols="3")
            aba_hist.append_row(["Data/Hora", "Pergunta do Usuário", "Resposta do Agente IA"])
            
        aba_hist.append_row([datetime.now().strftime("%d/%m/%Y %H:%M:%S"), pergunta, resposta])
    except Exception as e:
        print(f"Erro histórico: {e}")

# --- 4. CARREGAMENTO ---
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
    
    aba_rotas = planilha.worksheet("Rotas_Ativas").get_all_values()
    df_rotas = pd.DataFrame(aba_rotas[1:], columns=aba_rotas[0]) if len(aba_rotas) > 1 else pd.DataFrame()
    
    return {"contexto": f"ANP: {anp}\nFIPE: {fipe}\nANTT: {antt}", "tabela": df_rotas}

# --- 5. INTERFACE DO USUÁRIO ---
st.title("🚛 Inteligência de Fretes - Natura")

with st.sidebar:
    st.header("⚙️ Controle")
    if st.button("🔄 Atualizar Painel de Dados"):
        with st.spinner("Buscando dados recentes..."):
            st.cache_data.clear()
            st.success("Atualizado!")
            time.sleep(1)
            st.rerun()

try:
    dados = ler_base_sheets()
    contexto_ia, df_rotas = dados["contexto"], dados["tabela"]
except Exception as e:
    st.error(f"Erro de conexão.")
    df_rotas = pd.DataFrame()

if not df_rotas.empty:
    # Formata colunas para maiúsculo para busca inteligente
    df_rotas.columns = df_rotas.columns.astype(str).str.replace('\n', '').str.replace('\r', '').str.strip().str.upper()
    
    # BUSCA INTELIGENTE DE COLUNAS
    col_base = next((c for c in df_rotas.columns if 'CUSTO' in c and 'BASE' in c), None)
    col_contrato = next((c for c in df_rotas.columns if 'CONTRATO' in c), None)
    col_pedagio = next((c for c in df_rotas.columns if 'PEDAGIO' in c), None)
    col_vol = next((c for c in df_rotas.columns if 'VOL' in c), None)
    
    # Processamento de Custos
    base = df_rotas[col_base].apply(limpar_numero_br) if col_base else pd.Series([0.0]*len(df_rotas))
    contrato = df_rotas[col_contrato].apply(limpar_numero_br) if col_contrato else pd.Series([0.0]*len(df_rotas))
    pedagio = df_rotas[col_pedagio].apply(limpar_numero_br) if col_pedagio else pd.Series([0.0]*len(df_rotas))
    volume = df_rotas[col_vol].apply(limpar_numero_br) if col_vol else pd.Series([1.0]*len(df_rotas))
    volume = volume.apply(lambda x: 1.0 if x == 0 else x)
    
    # Se CUSTO BASE estiver zerado, usa o VALOR DE CONTRATO
    base = base.where(base > 0, contrato)
    
    df_rotas["CUSTO_TOTAL"] = base + pedagio
    df_rotas["Custo_Total_Ponderado"] = df_rotas["CUSTO_TOTAL"] * volume
    
    # KPIs
    st.markdown("### 🎯 Resumo da Operação (Ponderado)")
    col1, col2, col3, col4 = st.columns(4)
    
    total_rotas = len(df_rotas)
    total_volume = volume.sum()
    total_fretes = df_rotas["Custo_Total_Ponderado"].sum()
    custo_medio = total_fretes / total_volume if total_volume > 0 else 0
    
    col1.metric("Rotas Ativas", total_rotas)
    col2.metric("Volume Operado", f"{total_volume:,.0f}".replace(",", "."))
    col3.metric("Custo Médio Real", formatar_kpi_brl(custo_medio))
    col4.metric("Despesa Estimada", formatar_kpi_brl(total_fretes))

    st.divider()

    col_grafico, col_chat = st.columns([1.2, 1])

    with col_grafico:
        aba_barras, aba_mapa = st.tabs(["📊 Custo por CD", "🗺️ Mapa Operacional"])
        
        with aba_barras:
            col_origem = next((c for c in df_rotas.columns if 'ORIGEM' in c and ('ZONA' in c or 'DESCRI' in c)), None)
            if not col_origem: col_origem = next((c for c in df_rotas.columns if 'ORIGEM' in c), None)
            
            if col_origem:
                df_chart = df_rotas.groupby(col_origem)["Custo_Total_Ponderado"].sum().reset_index()
                df_chart = df_chart[df_chart["Custo_Total_Ponderado"] > 0]
                if not df_chart.empty:
                    df_chart = df_chart.rename(columns={col_origem: "CD de Origem", "Custo_Total_Ponderado": "Custo R$"})
                    st.bar_chart(df_chart.set_index("CD de Origem"), use_container_width=True)
                else:
                    st.warning("Valores de custo vieram zerados da base.")
            else:
                st.info("Coluna de Origem não encontrada.")

        with aba_mapa:
            col_lat_o = next((c for c in df_rotas.columns if 'LAT' in c and 'ORIG' in c), None)
            col_lon_o = next((c for c in df_rotas.columns if 'LON' in c and 'ORIG' in c), None)
            col_lat_d = next((c for c in df_rotas.columns if 'LAT' in c and 'DEST' in c), None)
            col_lon_d = next((c for c in df_rotas.columns if 'LON' in c and 'DEST' in c), None)
            
            if col_lat_o and col_lon_o and col_lat_d and col_lon_d:
                df_rotas['lat_origem'] = df_rotas[col_lat_o].apply(limpar_coordenada)
                df_rotas['lon_origem'] = df_rotas[col_lon_o].apply(limpar_coordenada)
                df_rotas['lat_destino'] = df_rotas[col_lat_d].apply(limpar_coordenada)
                df_rotas['lon_destino'] = df_rotas[col_lon_d].apply(limpar_coordenada)
                
                df_mapa = df_rotas.dropna(subset=['lat_origem', 'lon_origem', 'lat_destino', 'lon_destino'])
                
                if not df_mapa.empty:
                    st.caption(f"✨ Exibindo {len(df_mapa)} rotas no mapa.")
                    camada_arcos = pdk.Layer(
                        "ArcLayer", data=df_mapa,
                        get_source_position=["lon_origem", "lat_origem"],
                        get_target_position=["lon_destino", "lat_destino"],
                        get_source_color=[255, 140, 0, 160], 
                        get_target_color=[0, 200, 255, 160], 
                        get_width=3, pickable=True,
                    )
                    visao = pdk.ViewState(latitude=-15.78, longitude=-47.92, zoom=3.5, pitch=45)
                    st.pydeck_chart(pdk.Deck(layers=[camada_arcos], initial_view_state=visao, map_style="mapbox://styles/mapbox/dark-v10"))
                else:
                    st.warning("⚠️ Coordenadas inválidas após limpeza.")
            else:
                st.error("⚠️ Colunas de Latitude/Longitude não encontradas!")

    with col_chat:
        st.subheader("🤖 Agente Especialista & Base de Dados")
        instrucao = f"""Você é um Engenheiro Sênior. 
        Custo Real: Diesel(ANP)+5% Lubrificante+Fixos+10% Margem. ANTT: (Distância*CCD)+CC.
        REGRA: Se o usuário pedir para gerar dados/tabela, responda em formato Markdown puro (tabela com |).
        DADOS: {contexto_ia}"""
        
        if "chat" not in st.session_state:
            st.session_state.chat = genai.GenerativeModel("gemini-3.1-flash-lite-preview", system_instruction=instrucao).start_chat(history=[])
            st.session_state.msgs = []

        for m in st.session_state.msgs:
            with st.chat_message(m["role"]): st.markdown(m["content"])

        pergunta = st.chat_input("Ex: Gere uma base simulando rotas para o Norte...")
        if pergunta:
            st.chat_message("user").markdown(pergunta)
            st.session_state.msgs.append({"role": "user", "content": pergunta})
            
            with st.chat_message("assistant"):
                try:
                    with st.spinner("Pensando..."):
                        res = st.session_state.chat.send_message(pergunta).text
                    st.markdown(res)
                    st.session_state.msgs.append({"role": "assistant", "content": res})
                    salvar_historico_ia(pergunta, res)
                    
                    if "|" in res and "---" in res:
                        linhas = [l.strip() for l in res.split('\n') if '|' in l and '---' not in l]
                        if len(linhas) > 1:
                            csv_str = "\n".join([";".join([c.strip() for c in l.strip('|').split('|')]) for l in linhas])
                            st.download_button("📥 Baixar Base (CSV)", csv_str.encode('utf-8-sig'), "base_ia.csv", "text/csv")
                except Exception as e: 
                    st.error(f"Erro: {e}")
