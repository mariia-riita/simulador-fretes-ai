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
LINK_PLANILHA_SIMULACOES = "https://docs.google.com/spreadsheets/d/1o-cZbP27_Y0nUVvwdn2lT7q2AFja0MfLlexREF8f2Vc/edit?usp=sharing"

genai.configure(api_key=CHAVE_API_GEMINI)

# --- 3. MÁQUINAS DE LIMPEZA E SALVAMENTO DE DADOS ---
def limpar_numero_br(valor):
    """Converte valores financeiros para float, lidando com formatações malucas"""
    if pd.isna(valor): return 0.0
    v_str = str(valor).strip().upper().replace('\xa0', '').replace('\u202f', '')
    if v_str in ['', 'NAN', 'NULL', 'NONE', '-']: return 0.0
    
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
    """Salva o log de conversas na planilha principal"""
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
        pass

def salvar_simulacao_sheets(linhas_validas):
    """Injeta as tabelas geradas pela IA diretamente na nova planilha de simulações do usuário"""
    try:
        escopos = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        cred_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
        credenciais = ServiceAccountCredentials.from_json_keyfile_dict(cred_dict, escopos)
        cliente = gspread.authorize(credenciais)
        
        planilha_sim = cliente.open_by_url(LINK_PLANILHA_SIMULACOES)
        try:
            aba = planilha_sim.get_worksheet(0)
        except:
            aba = planilha_sim.sheet1
            
        valores_existentes = aba.get_all_values()
        data_atual = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        
        ia_header = linhas_validas[0]
        ia_dados = linhas_validas[1:]
        
        if len(valores_existentes) == 0:
            cabecalho_oficial = ["Data/Hora"] + ia_header
            aba.append_row(cabecalho_oficial)
            
        linhas_para_salvar = []
        for linha in ia_dados:
            if list(linha) == list(ia_header): continue
            linhas_para_salvar.append([data_atual] + list(linha))
            
        if linhas_para_salvar:
            aba.append_rows(linhas_para_salvar)
            return True
        return False
    except Exception as e:
        st.error(f"Erro ao salvar na planilha de simulações: {e}")
        return False

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
    
    return {"contexto": f"ANP: {anp}\nFIPE: {fipe}\nANTT: {antt}", "tabela": df_rotas, "anp_bruto": anp}

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
    df_anp = pd.DataFrame(dados["anp_bruto"])
except Exception as e:
    st.error("Erro de conexão.")
    df_rotas = pd.DataFrame()
    df_anp = pd.DataFrame()

# --- RADAR DO DIESEL NA SIDEBAR (CORRIGIDO) ---
if not df_anp.empty:
    with st.sidebar:
        st.write("---")
        st.header("⛽ Radar do Diesel S10")
        
        df_anp.columns = df_anp.columns.astype(str).str.strip().str.upper()
        col_preco_diesel = next((c for c in df_anp.columns if 'DIESEL' in c), None)
        col_sigla_estado = next((c for c in df_anp.columns if 'SIGLA' in c or 'ESTADO' in c), None)
        
        if col_preco_diesel and col_sigla_estado:
            df_anp[col_preco_diesel] = df_anp[col_preco_diesel].apply(limpar_numero_br)
            
            # PROTEÇÃO DA VÍRGULA: Se o valor vier como 670.00 ao invés de 6.70, divide por 100 automaticamente
            df_anp[col_preco_diesel] = df_anp[col_preco_diesel].apply(lambda x: x / 100.0 if x > 20.0 else x)
            
            diesel_medio_atual = df_anp[col_preco_diesel].mean()
            diesel_base_historico = 6.85
            variacao_diesel = diesel_medio_atual - diesel_base_historico
            
            # Mensagem contextualizada e clara por extenso
            st.caption(f"A média atual no país é de R$ {diesel_medio_atual:.2f} por litro.")
            
            # Indicador visual com o sufixo /L obrigatório
            st.metric(
                label="Preço Médio Nacional", 
                value=f"R$ {diesel_medio_atual:.2f} /L", 
                delta=f"{variacao_diesel:+.2f} /L vs ref",
                delta_color="inverse"
            )
            
            idx_max = df_anp[col_preco_diesel].idxmax()
            idx_min = df_anp[col_preco_diesel].idxmin()
            
            st.markdown(f"🔺 **Mais Caro:** {df_anp.loc[idx_max, col_sigla_estado]} — R$ {df_anp.loc[idx_max, col_preco_diesel]:.2f} /L")
            st.markdown(f"🔻 **Mais Barato:** {df_anp.loc[idx_min, col_sigla_estado]} — R$ {df_anp.loc[idx_min, col_preco_diesel]:.2f} /L")

if not df_rotas.empty:
    df_rotas.columns = df_rotas.columns.astype(str).str.replace('\n', '').str.replace('\r', '').str.strip().str.upper()
    
    col_base = next((c for c in df_rotas.columns if 'CUSTO' in c and 'BASE' in c), None)
    col_contrato = next((c for c in df_rotas.columns if 'CONTRATO' in c), None)
    col_frete = next((c for c in df_rotas.columns if 'FRETE' in c and 'CONS' in c), None)
    col_pedagio = next((c for c in df_rotas.columns if 'PEDAGIO' in c), None)
    col_vol = next((c for c in df_rotas.columns if 'VOL' in c), None)
    col_status = next((c for c in df_rotas.columns if 'STATUS' in c), None)
    
    base = df_rotas[col_base].apply(limpar_numero_br) if col_base else pd.Series([0.0]*len(df_rotas))
    contrato = df_rotas[col_contrato].apply(limpar_numero_br) if col_contrato else pd.Series([0.0]*len(df_rotas))
    frete_considerado = df_rotas[col_frete].apply(limpar_numero_br) if col_frete else pd.Series([0.0]*len(df_rotas))
    pedagio = df_rotas[col_pedagio].apply(limpar_numero_br) if col_pedagio else pd.Series([0.0]*len(df_rotas))
    volume = df_rotas[col_vol].apply(limpar_numero_br) if col_vol else pd.Series([1.0]*len(df_rotas))
    volume = volume.apply(lambda x: 1.0 if x == 0 else x)
    
    custo_principal = base.copy()
    custo_principal = custo_principal.where(custo_principal > 0, contrato)
    custo_principal = custo_principal.where(custo_principal > 0, frete_considerado)
    
    df_rotas["CUSTO_TOTAL"] = custo_principal + pedagio
    df_rotas["Custo_Total_Ponderado"] = df_rotas["CUSTO_TOTAL"] * volume
    
    if col_status:
        rotas_acima = len(df_rotas[df_rotas[col_status].astype(str).str.upper().str.contains('ACIMA', na=False)])
        rotas_abaixo = len(df_rotas[df_rotas[col_status].astype(str).str.upper().str.contains('ABAIXO', na=False)])
    else:
        rotas_acima = 0
        rotas_abaixo = 0
    
    st.markdown("### 🎯 Resumo da Operação (Ponderado)")
    col1, col2, col3, col4, col5 = st.columns(5)
    
    total_rotas = len(df_rotas)
    total_volume = volume.sum()
    total_fretes = df_rotas["Custo_Total_Ponderado"].sum()
    
    col1.metric("Rotas Ativas", total_rotas)
    col2.metric("Volume Operado", f"{total_volume:,.0f}".replace(",", "."))
    col3.metric("Despesa Estimada", formatar_kpi_brl(total_fretes))
    col4.metric("🔺 Acima da ANTT", f"{rotas_acima} rotas", help="Tarifas maiores que o piso mínimo. Foco de negociação e Saving!")
    col5.metric("🔻 Abaixo da ANTT", f"{rotas_abaixo} rotas", help="Tarifas abaixo do piso regulamentar por lei. Risco legal ou operacional.")

    st.divider()

    col_grafico, col_chat = st.columns([1.2, 1])

    with col_grafico:
        aba_barras, aba_mapa = st.tabs(["📊 Custo por CD", "🗺️ Mapa Operacional"])
        
        with aba_barras:
            st.markdown("### 📊 Custo por CD de Origem")
            col_origem = 'DESCRICAO_ZONA_DE_TRANSPORTE_ORIGEM'
            
            if col_origem in df_rotas.columns:
                df_rotas[col_origem] = df_rotas[col_origem].astype(str).str.strip().str.upper()
                df_chart = df_rotas.groupby(col_origem)["Custo_Total_Ponderado"].sum().reset_index()
                
                df_chart = df_chart[(df_chart["Custo_Total_Ponderado"] > 0) & (df_chart["Custo_Total_Ponderado"] < 50000000)]
                
                if not df_chart.empty:
                    df_chart = df_chart.sort_values(by="Custo_Total_Ponderado", ascending=False)
                    df_chart = df_chart.rename(columns={col_origem: "CD de Origem", "Custo_Total_Ponderado": "Custo R$"})
                    st.bar_chart(df_chart.set_index("CD de Origem"), use_container_width=True, color="#FF6600")
                else:
                    st.warning("⚠️ Os valores de custo calculados vieram zerados ou são todos anomalias.")
            else:
                st.error("🚨 A coluna 'DESCRICAO_ZONA_DE_TRANSPORTE_ORIGEM' não foi encontrada!")

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
                    st.caption(f"✨ Exibindo {len(df_mapa)} rotas conectadas no mapa.")
                    camada_origens = pdk.Layer(
                        "ScatterplotLayer", data=df_mapa, get_position=["lon_origem", "lat_origem"],
                        get_color=[255, 140, 0, 200], get_radius=15000, pickable=True
                    )
                    camada_destinos = pdk.Layer(
                        "ScatterplotLayer", data=df_mapa, get_position=["lon_destino", "lat_destino"],
                        get_color=[0, 200, 255, 200], get_radius=15000, pickable=True
                    )
                    camada_arcos = pdk.Layer(
                        "ArcLayer", data=df_mapa, get_source_position=["lon_origem", "lat_origem"],
                        get_target_position=["lon_destino", "lat_destino"], get_source_color=[255, 140, 0, 160], 
                        get_target_color=[0, 200, 255, 160], get_width=3, pickable=True,
                    )
                    visao = pdk.ViewState(latitude=-15.78, longitude=-47.92, zoom=3.5, pitch=45)
                    st.pydeck_chart(pdk.Deck(layers=[camada_origens, camada_destinos, camada_arcos], initial_view_state=visao, map_style=None))
                else:
                    st.warning("⚠️ As coordenadas limpas não geraram pontos válidos.")
            else:
                st.error("⚠️ Colunas de Latitude/Longitude não encontradas!")

    with col_chat:
        st.subheader("🤖 Agente Estratégico de Fretes")
        
        contexto_ia_expandido = contexto_ia + f"\n\n[MÉTRICAS DA OPERAÇÃO REAL NATURA]:\n- Total de Rotas na Tabela: {len(df_rotas)}\n- Rotas com frete ACIMA do Mínimo ANTT: {rotas_acima}\n- Rotas com frete ABAIXO do Mínimo ANTT: {rotas_abaixo}\nColunas analíticas de desvios disponíveis na tabela: 'FRETE MINIMO', 'DIF R$', 'DIF - %', 'STATUS'."
        
        instrucao = f"""Você é um Engenheiro de Logística Sênior e Consultor Estratégico da Natura.
        Sua missão principal é responder à pergunta de ouro: "Onde estão as minhas oportunidades de saving no frete pesado?"

        === DETECÇÃO AUTOMÁTICA DE GARGALOS, MALEZAS E PROBLEMAS (Baseado no Formulário) ===
        Sempre que o usuário perguntar sobre gargalos, problemas na operação, anomalias ou o que deve ser corrigido, faça esse diagnóstico de forma automática com base nos dados:
        1. Anomalias do OTM (Erros de Digitação): Erros graves de digitação na planilha onde códigos de rastreamento, notas fiscais ou CNPJs entram nas colunas de frete, gerando faturamentos absurdos (Exemplo real: caso de Murici marcando 23 bilhões fictícios). 
        2. Subutilização de Ativos (Capacidade Desperdiçada): Identificar rotas operando com baixo peso/volume faturado, mas utilizando Carretas pesadas (5 ou 6 eixos). Sugira agressivamente o uso de veículos menores usando os parâmetros abaixo e calcule a oportunidade de ganho.
        3. Falta de Histórico de Simulações: Perda crônica de inteligência devido a simulações de frete soltas (resolvido salvando direto na nova planilha conectada).
        4. Oportunidade vs. Mercado: Se a tarifa contratada está muito acima do Should Cost, aponte como Oportunidade de Negociação imediata. Se houver justificativa regional (falta de frete de retorno, alto risco de roubo de carga), classifique como Questão de Mercado.

        === PARÂMETROS DE FROTA LEVE (Cravados na sua memória - Não estão na planilha) ===
        Use estes números exatos para simular Should Cost de veículos menores quando o volume for baixo:
        * Carreta (6 Eixos): Capacidade 26-32 Ton | Consumo: 2.2 km/L
        * Carreta (5 Eixos): Capacidade 20-25 Ton | Consumo: 2.5 km/L
        * Truck (3 Eixos): Capacidade 14 Ton | Consumo: 3.5 km/L | FIPE ref: R$ 350.000
        * Toco (2 Eixos): Capacidade 7-8 Ton | Consumo: 4.5 km/L | FIPE ref: R$ 250.000
        * VUC Urbano (2 Eixos): Capacidade 3-4 Ton | Consumo: 6.5 km/L | FIPE ref: R$ 150.000

        === DIRETRIZES DE ANÁLISE ===
        1. O Frete Mais Justo: Calcule o 'Should Cost' cruzando os dados de consumo acima com o Diesel (ANP) e as taxas estaduais. Compare com o Piso ANTT e os valores contratuais vigentes.
        2. Análise de Desvios (Mínimo Regulamentar): Use as colunas de FRETE MINIMO, DIF R$', 'DIF - %' e STATUS.
           - STATUS "ACIMA": Alerte que são focos claros de saving.
           - STATUS "ABAIXO": Alerte que indicam potencial risco de conformidade legal com a ANTT ou transportador operando no prejuízo.
        3. Contratação Regional: Indique o modelo ideal para cada região (Ex: Frota Dedicada para rotas curtas de alto volume vs Spot/Lotação).

        REGRA DO GERADOR: Se for solicitado gerar uma base de dados ou simulações, responda obrigatoriamente em formato de Tabela Markdown (separada por |).

        DADOS DE CONSULTA DA BASE NATURA: {contexto_ia_expandido}"""
        
        if "chat" not in st.session_state:
            st.session_state.chat = genai.GenerativeModel("gemini-3.1-flash-lite-preview", system_instruction=instrucao).start_chat(history=[])
            st.session_state.msgs = []

        for m in st.session_state.msgs:
            with st.chat_message(m["role"]): st.markdown(m["content"])

        pergunta = st.chat_input("Ex: Quais rotas estão acima do mínimo e quais são os gargalos?")
        if pergunta:
            st.chat_message("user").markdown(pergunta)
            st.session_state.msgs.append({"role": "user", "content": pergunta})
            
            with st.chat_message("assistant"):
                try:
                    with st.spinner("Analisando mercado e diagnosticando problemas..."):
                        res = st.session_state.chat.send_message(pergunta).text
                    st.markdown(res)
                    st.session_state.msgs.append({"role": "assistant", "content": res})
                    salvar_historico_ia(pergunta, res)
                    
                    if "|" in res and "---" in res:
                        linhas = res.split('\n')
                        linhas_tabela = [l.strip() for l in linhas if '|' in l]
                        
                        linhas_validas = []
                        for l in linhas_tabela:
                            if '---' in l: continue
                            cols = [c.strip() for c in l.strip('|').split('|')]
                            if len(cols) > 1:
                                linhas_validas.append(cols)
                        
                        if len(linhas_validas) > 1:
                            with st.spinner("Carregando simulação direto no Google Sheets..."):
                                sucesso = salvar_simulacao_sheets(linhas_validas)
                            if sucesso:
                                st.success("✨ Nova base de simulação carregada com sucesso na sua planilha consolidada!")
                                st.markdown(f"🔗 [Clique aqui para abrir a Planilha de Simulações]({LINK_PLANILHA_SIMULACOES})")
                                
                except Exception as e: 
                    st.error(f"Erro: {e}")
else:
    st.info("Planilha vazia ou carregando...")
