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
    st.error("Erro de conexão.")
    df_rotas = pd.DataFrame()

if not df_rotas.empty:
    df_rotas.columns = df_rotas.columns.astype(str).str.replace('\n', '').str.replace('\r', '').str.strip().str.upper()
    
    col_base = next((c for c in df_rotas.columns if 'CUSTO' in c and 'BASE' in c), None)
    col_contrato = next((c for c in df_rotas.columns if 'CONTRATO' in c), None)
    col_frete = next((c for c in df_rotas.columns if 'FRETE' in c and 'CONS' in c), None)
    col_pedagio = next((c for c in df_rotas.columns if 'PEDAGIO' in c), None)
    col_vol = next((c for c in df_rotas.columns if 'VOL' in c), None)
    
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
        # Adicionada a aba de Gestão & Produtividade
        aba_barras, aba_mapa, aba_gestao = st.tabs(["📊 Custo por CD", "🗺️ Mapa Operacional", "📋 Gestão & Produtividade"])
        
        with aba_barras:
            st.markdown("### 📊 Custo por CD de Origem")
            col_origem = 'DESCRICAO_ZONA_DE_TRANSPORTE_ORIGEM'
            
            if col_origem in df_rotas.columns:
                df_rotas[col_origem] = df_rotas[col_origem].astype(str).str.strip().str.upper()
                df_chart = df_rotas.groupby(col_origem)["Custo_Total_Ponderado"].sum().reset_index()
                
                # ESCUDO ANTI-ANOMALIAS
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
                    st.warning("⚠️ As coordenadas limpadas não geraram pontos válidos.")
            else:
                st.error("⚠️ Colunas de Latitude/Longitude não encontradas!")
                
        with aba_gestao:
            
            st.divider()
            st.markdown("### 🎯 Formulário de Pesquisa: Problemas Mapeados e Foco de Soluções")
            st.markdown("""
            Com base nos levantamentos estruturais da operação de Frete Pesado da Natura, o Agente de IA foi projetado para atuar diretamente nos seguintes problemas-foco:
            * **Anomalias Visíveis de Faturamento:** Bloqueio imediato de erros operacionais de digitação inseridos no OTM (como custos acidentais na casa dos bilhões de reais, gerados por códigos de rastreio ou CNPJs inseridos nas colunas de frete).
            * **Subutilização de Ativos (Capacidade Desperdiçada):** Identificar quando uma Carreta de 6 eixos foi contratada e cobrada para movimentar volumes leves, propondo imediatamente o downgrade financeiro para veículos menores (Truck/Toco).
            * **Falta de Memória de Negociação:** Eliminar a perda de dados de simulações diárias feitas pelos analistas, forçando a IA a gravar cada cenário estratégico diretamente em uma base de dados estruturada no Google Sheets de forma cronológica.
            * **Desalinhamento com o Piso ANTT e Should Cost:** Identificar em tempo real se os contratos vigentes estão coerentes com a realidade de custos de mercado ou se existem flutuações sazonais de retorno vazio que exijam novos modelos de contratação dedicada.
            """)

    with col_chat:
        st.subheader("🤖 Agente Estratégico de Fretes")
        
        # O CÉREBRO ATUALIZADO COM OS REQUISITOS DA GESTÃO DO PROJETO
        instrucao = f"""Você é um Engenheiro de Logística Sênior e Consultor Estratégico da Natura.
        Sua missão principal é responder à pergunta de ouro: "Onde estão as minhas oportunidades de saving no frete pesado?"

        === PARÂMETROS DE FROTA (Use para simular Should Cost de veículos menores) ===
        * Carreta (6 Eixos): Capacidade 26-32 Ton | Consumo: 2.2 km/L
        * Carreta (5 Eixos): Capacidade 20-25 Ton | Consumo: 2.5 km/L
        * Truck (3 Eixos): Capacidade 14 Ton | Consumo: 3.5 km/L | FIPE ref: R$ 350.000
        * Toco (2 Eixos): Capacidade 7-8 Ton | Consumo: 4.5 km/L | FIPE ref: R$ 250.000
        * VUC Urbano (2 Eixos): Capacidade 3-4 Ton | Consumo: 6.5 km/L | FIPE ref: R$ 150.000

        === GESTÃO DO PROJETO E ROI (Mapeado por Maria Rita Ferreira Soares) ===
        * Ganho de tempo: O processo manual demorava 16h/mês; com a IA demora 5 minutos (15h55min economizadas por mês, 99.5% de ganho de produtividade).
        * Cronograma: Etapa 1 (Validação Regras - 1 Semana); Etapa 2 (Frota Leve - 2 Semanas); Etapa 3 (Homologação - 3 Semanas); Etapa 4 (Automatização Completa - 1 Mês).
        * Problemas Foco do Formulário: Bloqueio de anomalias bilionárias de digitação do OTM, identificação de subutilização de frota (carretas vazias), falta de histórico de simulação (resolvido salvando no Sheets) e desalinhamento ANTT/Should Cost.

        === DIRETRIZES DE ANÁLISE ===
        1. O Frete Mais Justo: Calcule o 'Should Cost' cruzando os dados de consumo acima com o Diesel (ANP) e as taxas estaduais. Compare-o com o Piso ANTT e com o custo que a Natura está a pagar.
        2. Veículos Menores: Se o usuário perguntar sobre rotas específicas e o volume for compatível, sugira agressivamente o uso de Truck, Toco ou VUC para reduzir os custos (mostre a simulação matemática do saving).
        3. Diagnóstico de Anomalias: Se a Natura estiver pagando muito acima da ANTT/Should Cost, classifique como "Oportunidade de Negociação". Se for justificável, explique como "Questão de Mercado" (risco de roubo, frete de retorno vazio, sazonalidade).
        4. Contratação: Indique o modelo ideal para cada região (Ex: Frota Dedicada para rotas curtas de alto volume vs Spot/Lotação).
        
        REGRA DO GERADOR: Se for solicitado gerar uma base de dados ou simulações, responda obrigatoriamente em formato de Tabela Markdown (separada por |).
        
        DADOS DE CONSULTA DA BASE NATURA (ANP, FIPE, ANTT, Taxas): {contexto_ia}"""
        
        if "chat" not in st.session_state:
            st.session_state.chat = genai.GenerativeModel("gemini-3.1-flash-lite-preview", system_instruction=instrucao).start_chat(history=[])
            st.session_state.msgs = []

        for m in st.session_state.msgs:
            with st.chat_message(m["role"]): st.markdown(m["content"])

        pergunta = st.chat_input("Ex: Onde estão as minhas oportunidades de saving?")
        if pergunta:
            st.chat_message("user").markdown(pergunta)
            st.session_state.msgs.append({"role": "user", "content": pergunta})
            
            with st.chat_message("assistant"):
                try:
                    with st.spinner("Analisando mercado e calculando savings..."):
                        res = st.session_state.chat.send_message(pergunta).text
                    st.markdown(res)
                    st.session_state.msgs.append({"role": "assistant", "content": res})
                    salvar_historico_ia(pergunta, res)
                    
                    if "|" in res and "---" in res:
                        linhas = res.split('\n')
                        linhas_tabela = [l.strip() for l in lines if '|' in l]
                        
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
