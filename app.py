from datetime import datetime
import io
import json
import time
import google.generativeai as genai
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import pydeck as pdk
import requests
import streamlit as st
import streamlit.components.v1 as components

# --- 1. CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Should Cost IA - Natura", page_icon="🚛", layout="wide"
)

# --- 1.1 FONTE POPPINS CUSTOMIZADA ---
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap');

    html, body, [data-testid="stAppViewContainer"], .stApp {
        font-family: 'Poppins', sans-serif;
    }
    
    h1, h2, h3, h4, h5, h6, p, label, button, .stButton>button {
        font-family: 'Poppins', sans-serif !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- 2. CONSTANTES E SEGURANÇA ---
CHAVE_API_GEMINI = st.secrets["GEMINI_API_KEY"]
LINK_PLANILHA = "https://docs.google.com/spreadsheets/d/12TSlwkvaklIWr4NBkAeM11vSfj9K_ycFZzqyGW9ImX0/edit?usp=sharing"
LINK_PLANILHA_SIMULACOES = "https://docs.google.com/spreadsheets/d/1o-cZbP27_Y0nUVvwdn2lT7q2AFja0MfLlexREF8f2Vc/edit?usp=sharing"
LINK_POWERBI_ANP = "https://app.powerbi.com/view?r=eyJrIjoiMGM0NDhhMTUtMjQwZi00N2RlLTk1M2UtYjkxZTlkNzM1YzE5IiwidCI6IjQ0OTlmNGZmLTI0YTYtNGI0Mi1iN2VmLTEyNGFmY2FkYzkxMyJ9"

genai.configure(api_key=CHAVE_API_GEMINI)


# --- 3. MÁQUINAS DE LIMPEZA E SALVAMENTO DE DADOS ---
def limpar_numero_br(valor):
  """Converte valores financeiros para float, lidando com formatações malucas"""
  if pd.isna(valor):
    return 0.0
  v_str = str(valor).strip().upper().replace("\xa0", "").replace("\u202f", "")
  if v_str in ["", "NAN", "NULL", "NONE", "-"]:
    return 0.0

  v_str = (
      v_str.replace("R$", "")
      .replace("$", "")
      .replace(" ", "")
      .replace('"', "")
      .replace("%", "")
  )
  if "." in v_str and "," in v_str:
    v_str = v_str.replace(".", "").replace(",", ".")
  elif "," in v_str:
    v_str = v_str.replace(",", ".")

  try:
    return float(v_str)
  except:
    return 0.0


def limpar_coordenada(coord):
  """Recupera coordenadas mesmo se estiverem formatadas como porcentagem (%), com graus ou vírgulas"""
  if pd.isna(coord):
    return None
  c_str = str(coord).strip().replace('"', "").replace(" ", "").replace("°", "")

  eh_porcentagem = "%" in c_str
  c_str = c_str.replace("%", "")

  if not c_str or c_str.upper() in ["NAN", "NULL", "NONE", "-", ""]:
    return None

  if "." in c_str and "," in c_str:
    c_str = c_str.replace(".", "").replace(",", ".")
  elif "," in c_str:
    c_str = c_str.replace(",", ".")
  elif c_str.count(".") > 1:
    c_str = c_str.replace(".", "")

  try:
    val = float(c_str)
    if val == 0.0:
      return None

    if eh_porcentagem:
      val = val / 100.0

    while abs(val) > 180:
      val = val / 10.0

    return val
  except:
    return None


def formatar_kpi_brl(valor):
  if pd.isna(valor) or valor == 0:
    return "R$ 0,00"
  valor_em_milhares = valor / 1000.0
  return f"R$ {valor_em_milhares:,.0f} mil".replace(",", ".")


def salvar_historico_ia(pergunta, resposta):
  """Salva o log de conversas na planilha principal"""
  try:
    escopos = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    cred_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    credenciais = ServiceAccountCredentials.from_json_keyfile_dict(
        cred_dict, escopos
    )
    cliente = gspread.authorize(credenciais)
    planilha = cliente.open_by_url(LINK_PLANILHA)

    try:
      aba_hist = planilha.worksheet("Historico_Simulacoes")
    except:
      aba_hist = planilha.add_worksheet(
          title="Historico_Simulacoes", rows="1000", cols="3"
      )
      aba_hist.append_row(
          ["Data/Hora", "Pergunta do Usuário", "Resposta do Agente IA"]
      )

    aba_hist.append_row([
        datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        pergunta,
        resposta,
    ])
  except Exception:
    pass


def salvar_simulacao_sheets(linhas_validas):
  """Injeta as tabelas geradas pela IA diretamente na nova planilha de simulações do usuário"""
  try:
    escopos = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    cred_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    credenciais = ServiceAccountCredentials.from_json_keyfile_dict(
        cred_dict, escopos
    )
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
      if list(linha) == list(ia_header):
        continue
      linhas_para_salvar.append([data_atual] + list(linha))

    if linhas_para_salvar:
      aba.append_rows(linhas_para_salvar)
      return True
    return False
  except Exception as e:
    st.error(f"Erro ao salvar na planilha de simulações: {e}")
    return False


# --- 4. CARREGAMENTO DE DADOS ---
@st.cache_data(ttl=300)
def ler_base_sheets():
  escopos = [
      "https://spreadsheets.google.com/feeds",
      "https://www.googleapis.com/auth/drive",
  ]
  cred_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
  credenciais = ServiceAccountCredentials.from_json_keyfile_dict(
      cred_dict, escopos
  )
  cliente = gspread.authorize(credenciais)
  planilha = cliente.open_by_url(LINK_PLANILHA)

  anp = planilha.worksheet("Apoio_ANP").get_all_records()
  fipe = planilha.worksheet("Apoio_FIPE").get_all_records()
  antt = planilha.worksheet("Apoio_ANTT").get_all_records()

  try:
    param_custos = planilha.worksheet("Parametros_Custos").get_all_records()
  except:
    param_custos = []

  aba_rotas = planilha.worksheet("Rotas_Ativas").get_all_values()
  df_rotas = (
      pd.DataFrame(aba_rotas[1:], columns=aba_rotas[0])
      if len(aba_rotas) > 1
      else pd.DataFrame()
  )

  return {
      "contexto": (
          f"ANP (Preço Diesel): {anp}\nFIPE (Preço Veículos): {fipe}\nANTT (Piso"
          f" Mínimo): {antt}\nParâmetros Custos Fixos & Impostos:"
          f" {param_custos}"
      ),
      "tabela": df_rotas,
      "anp_bruto": anp,
  }


@st.cache_data(ttl=3600)
def buscar_diesel_anp_live(df_anp_backup):
  """Busca o arquivo de dados abertos da ANP via Python.

  Se o servidor do governo falhar, usa o Google Sheets como backup.
  """
  url_anp = "https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/shpc/dsan/semanal-estados.csv"
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
          " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
      )
  }

  try:
    resposta = requests.get(url_anp, headers=headers, timeout=6)
    if resposta.status_code == 200:
      df_live = pd.read_csv(
          io.BytesIO(resposta.content), sep=";", encoding="iso-8859-1"
      )
      if not df_live.empty:
        return df_live
  except Exception:
    pass

  return df_anp_backup


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
  df_anp_backup = pd.DataFrame(dados["anp_bruto"])
except Exception as e:
  st.error(f"Erro de conexão real com o Google Sheets: {e}")
  df_rotas = pd.DataFrame()
  df_anp_backup = pd.DataFrame()

# --- RADAR DO DIESEL NA SIDEBAR (100% AUTOMÁTICO EM PYTHON) ---
df_anp_processar = buscar_diesel_anp_live(df_anp_backup)

if not df_anp_processar.empty:
  with st.sidebar:
    st.write("---")
    st.header("⛽ Radar do Diesel S10")

    df_anp_processar.columns = (
        df_anp_processar.columns.astype(str).str.strip().str.upper()
    )

    col_prod = next(
        (c for c in df_anp_processar.columns if "PRODUTO" in c), None
    )
    if col_prod:
      df_anp_processar = df_anp_processar[
          df_anp_processar[col_prod]
          .astype(str)
          .str.upper()
          .str.contains("DIESEL S10|DIESEL_S10", na=False)
      ]

    col_preco_diesel = next(
        (
            c
            for c in df_anp_processar.columns
            if ("PRECO" in c or "PREÇO" in c) and ("MEDIO" in c or "MÉDIO" in c)
        ),
        None,
    )
    if not col_preco_diesel:
      col_preco_diesel = next(
          (
              c
              for c in df_anp_processar.columns
              if ("DIESEL" in c or "REVENDA" in c or "PRECO" in c)
              and "POSTO" not in c
              and "QTD" not in c
              and "NUMERO" not in c
          ),
          None,
      )

    col_sigla_estado = next(
        (
            c
            for c in df_anp_processar.columns
            if "SIGLA" in c or "ESTADO" in c or "UF" in c
        ),
        None,
    )

    if col_preco_diesel and col_sigla_estado:
      df_anp_processar[col_preco_diesel] = df_anp_processar[
          col_preco_diesel
      ].apply(limpar_numero_br)
      df_anp_processar[col_preco_diesel] = df_anp_processar[
          col_preco_diesel
      ].apply(lambda x: x / 100.0 if x > 20.0 else x)

      df_diesel_valido = df_anp_processar[
          df_anp_processar[col_preco_diesel] > 1.0
      ].copy()
      df_diesel_valido = df_diesel_valido[
          ~df_diesel_valido[col_sigla_estado]
          .astype(str)
          .str.upper()
          .isin(["BR", "BRASIL"])
      ]

      if not df_diesel_valido.empty:
        diesel_medio_atual = df_diesel_valido[col_preco_diesel].mean()

        st.metric(
            label="Preço Médio Nacional",
            value=f"R$ {diesel_medio_atual:.2f} /L",
        )

        idx_max = df_diesel_valido[col_preco_diesel].idxmax()
        idx_min = df_diesel_valido[col_preco_diesel].idxmin()

        st.markdown(
            "🔺 **Mais Caro:**"
            f" {df_diesel_valido.loc[idx_max, col_sigla_estado]} — R$"
            f" {df_diesel_valido.loc[idx_max, col_preco_diesel]:.2f} /L"
        )
        st.markdown(
            "🔻 **Mais Barato:**"
            f" {df_diesel_valido.loc[idx_min, col_sigla_estado]} — R$"
            f" {df_diesel_valido.loc[idx_min, col_preco_diesel]:.2f} /L"
        )

if not df_rotas.empty:
  df_rotas.columns = (
      df_rotas.columns.astype(str)
      .str.replace("\n", "")
      .str.replace("\r", "")
      .str.strip()
      .str.upper()
  )

  col_base = next(
      (c for c in df_rotas.columns if "CUSTO" in c and "BASE" in c), None
  )
  col_contrato = next((c for c in df_rotas.columns if "CONTRATO" in c), None)
  col_frete = next(
      (c for c in df_rotas.columns if "FRETE" in c and "CONS" in c), None
  )
  col_pedagio = next((c for c in df_rotas.columns if "PEDAGIO" in c), None)
  col_vol = next((c for c in df_rotas.columns if "VOL" in c), None)
  col_status = next((c for c in df_rotas.columns if "STATUS" in c), None)

  base = (
      df_rotas[col_base].apply(limpar_numero_br)
      if col_base
      else pd.Series([0.0] * len(df_rotas))
  )
  contrato = (
      df_rotas[col_contrato].apply(limpar_numero_br)
      if col_contrato
      else pd.Series([0.0] * len(df_rotas))
  )
  frete_considerado = (
      df_rotas[col_frete].apply(limpar_numero_br)
      if col_frete
      else pd.Series([0.0] * len(df_rotas))
  )
  pedagio = (
      df_rotas[col_pedagio].apply(limpar_numero_br)
      if col_pedagio
      else pd.Series([0.0] * len(df_rotas))
  )
  volume = (
      df_rotas[col_vol].apply(limpar_numero_br)
      if col_vol
      else pd.Series([1.0] * len(df_rotas))
  )
  volume = volume.apply(lambda x: 1.0 if x == 0 else x)

  custo_principal = base.copy()
  custo_principal = custo_principal.where(custo_principal > 0, contrato)
  custo_principal = custo_principal.where(
      custo_principal > 0, frete_considerado
  )

  df_rotas["CUSTO_TOTAL"] = custo_principal + pedagio
  df_rotas["Custo_Total_Ponderado"] = df_rotas["CUSTO_TOTAL"] * volume

  if col_status:
    rotas_dentro = len(
        df_rotas[
            df_rotas[col_status]
            .astype(str)
            .str.upper()
            .str.contains("DENTRO", na=False)
        ]
    )
    rotas_abaixo = len(
        df_rotas[
            df_rotas[col_status]
            .astype(str)
            .str.upper()
            .str.contains("ABAIXO", na=False)
        ]
    )
  else:
    rotas_dentro = 0
    rotas_abaixo = 0

  st.markdown("### 🎯 Resumo da Operação (Ponderado)")
  col1, col2, col3, col4, col5 = st.columns(5)

  total_rotas = len(df_rotas)
  total_volume = volume.sum()

  df_fretes_reais = df_rotas[df_rotas["Custo_Total_Ponderado"] < 50000000]
  total_fretes = df_fretes_reais["Custo_Total_Ponderado"].sum()

  col1.metric("Rotas Ativas", total_rotas)
  col2.metric("Volume Operado", f"{total_volume:,.0f}".replace(",", "."))
  col3.metric("Despesa Estimada", formatar_kpi_brl(total_fretes))
  col4.metric(
      "🔺 Dentro da ANTT",
      f"{rotas_dentro} rotas",
      help="Tarifas maiores que o piso mínimo. Foco de negociação e Saving!",
  )
  col5.metric(
      "🔻 Abaixo da ANTT",
      f"{rotas_abaixo} rotas",
      help=(
          "Tarifas abaixo do piso regulamentar por lei. Risco legal ou"
          " operacional."
      ),
  )

  st.divider()

  col_grafico, col_chat = st.columns([1.3, 1])

  with col_grafico:
    aba_barras, aba_mapa, aba_anp_pbi = st.tabs(
        ["📊 Custo por CD", "🗺️ Mapa Operacional", "⛽ Painel ANP Oficial"]
    )

    with aba_barras:
      st.markdown("### 📊 Custo por CD de Origem")
      col_origem = "DESCRICAO_ZONA_DE_TRANSPORTE_ORIGEM"

      if col_origem in df_rotas.columns:
        df_rotas[col_origem] = (
            df_rotas[col_origem].astype(str).str.strip().str.upper()
        )
        df_chart = (
            df_rotas.groupby(col_origem)["Custo_Total_Ponderado"]
            .sum()
            .reset_index()
        )

        df_chart = df_chart[
            (df_chart["Custo_Total_Ponderado"] > 0)
            & (df_chart["Custo_Total_Ponderado"] < 50000000)
        ]

        if not df_chart.empty:
          df_chart = df_chart.sort_values(
              by="Custo_Total_Ponderado", ascending=False
          )
          df_chart = df_chart.rename(
              columns={
                  col_origem: "CD de Origem",
                  "Custo_Total_Ponderado": "Custo R$",
              }
          )
          st.bar_chart(
              df_chart.set_index("CD de Origem"),
              use_container_width=True,
              color="#FF6600",
          )
        else:
          st.warning(
              "⚠️ Os valores de custo calculados vieram zerados ou são todos"
              " anomalias."
          )
      else:
        st.error(
            "🚨 A coluna 'DESCRICAO_ZONA_DE_TRANSPORTE_ORIGEM' não foi"
            " encontrada!"
        )

    with aba_mapa:
      col_lat_o = next(
          (c for c in df_rotas.columns if "LAT" in c and "ORIG" in c), None
      )
      col_lon_o = next(
          (c for c in df_rotas.columns if "LON" in c and "ORIG" in c), None
      )
      col_lat_d = next(
          (c for c in df_rotas.columns if "LAT" in c and "DEST" in c), None
      )
      col_lon_d = next(
          (c for c in df_rotas.columns if "LON" in c and "DEST" in c), None
      )

      if col_lat_o and col_lon_o and col_lat_d and col_lon_d:
        df_rotas["lat_origem"] = df_rotas[col_lat_o].apply(limpar_coordenada)
        df_rotas["lon_origem"] = df_rotas[col_lon_o].apply(limpar_coordenada)
        df_rotas["lat_destino"] = df_rotas[col_lat_d].apply(limpar_coordenada)
        df_rotas["lon_destino"] = df_rotas[col_lon_d].apply(limpar_coordenada)

        df_mapa = df_rotas.dropna(
            subset=["lat_origem", "lon_origem", "lat_destino", "lon_destino"]
        )

        if not df_mapa.empty:
          st.caption(
              f"✨ Sucesso! Exibindo {len(df_mapa)} rotas conectadas no mapa."
          )
          camada_origens = pdk.Layer(
              "ScatterplotLayer",
              data=df_mapa,
              get_position=["lon_origem", "lat_origem"],
              get_color=[255, 140, 0, 200],
              get_radius=15000,
              pickable=True,
          )
          camada_destinos = pdk.Layer(
              "ScatterplotLayer",
              data=df_mapa,
              get_position=["lon_destino", "lat_destino"],
              get_color=[0, 200, 255, 200],
              get_radius=15000,
              pickable=True,
          )
          camada_arcos = pdk.Layer(
              "ArcLayer",
              data=df_mapa,
              get_source_position=["lon_origem", "lat_origem"],
              get_target_position=["lon_destino", "lat_destino"],
              get_source_color=[255, 140, 0, 160],
              get_target_color=[0, 200, 255, 160],
              get_width=3,
              pickable=True,
          )
          visao = pdk.ViewState(
              latitude=-15.78, longitude=-47.92, zoom=3.5, pitch=45
          )
          st.pydeck_chart(
              pdk.Deck(
                  layers=[camada_origens, camada_destinos, camada_arcos],
                  initial_view_state=visao,
                  map_style=None,
              )
          )
        else:
          st.warning("⚠️ As coordenadas limpas não geraram pontos válidos.")
      else:
        st.error("⚠️ Colunas de Latitude/Longitude não encontradas!")

    # 🖥️ ABA EXCLUSIVA DO POWERBI DA ANP
    with aba_anp_pbi:
      st.caption(
          "🔗 Consulta em tempo real do Painel Oficial de Preços de"
          " Combustíveis da ANP."
      )

      st.link_button(
          "🌐 Abrir Painel Oficial da ANP em Nova Aba",
          LINK_POWERBI_ANP,
          type="primary",
      )
      st.write("---")

      html_pbi = f"""
      <iframe title="Painel ANP" width="100%" height="650" src="{LINK_POWERBI_ANP}" frameborder="0" allowFullScreen="true" style="border:0; border-radius:10px;"></iframe>
      """
      components.html(html_pbi, height=670)

  with col_chat:
    st.subheader("🤖 Agente Estratégico de Fretes")

    resumo_rotas_abaixo = ""
    if not df_rotas.empty and "STATUS" in df_rotas.columns:
      df_temp = df_rotas.copy()
      df_temp["STATUS_CLEAN"] = (
          df_temp["STATUS"].astype(str).str.strip().str.lower()
      )
      df_abaixo_real = df_temp[
          df_temp["STATUS_CLEAN"].str.contains("abaixo", na=False)
      ].copy()

      if "DIF R$ ANTT" in df_abaixo_real.columns:
        df_abaixo_real["DIF_R$_NUM"] = df_abaixo_real["DIF R$ ANTT"].apply(
            limpar_numero_br
        )
        top_15_abaixo = df_abaixo_real.sort_values(
            by="DIF_R$_NUM", ascending=True
        ).head(15)

        cols_prompt = [
            "NOME_TRANSPORTADORA",
            "DESCRICAO_ZONA_DE_TRANSPORTE_ORIGEM",
            "DESCRICAO_ZONA_DE_TRANSPORTE_DESTINO",
            "PERFIL_GRUPO_DE_EQUIPAMENTO",
            "Frete Considerado",
            "Frete Minimo",
            "DIF R$ ANTT",
            "DIF - %",
        ]
        cols_presentes = [c for c in cols_prompt if c in top_15_abaixo.columns]
        resumo_rotas_abaixo = top_15_abaixo[cols_presentes].to_string(
            index=False
        )

    contexto_ia_expandido = (
        contexto_ia
        + f"\n\n[MÉTRICAS DA OPERAÇÃO REAL NATURA]:\n- Total de Rotas na Tabela:"
        f" {len(df_rotas)}\n- Rotas com frete DENTRO do Mínimo ANTT:"
        f" {rotas_dentro}\n- Rotas com frete ABAIXO do Mínimo ANTT:"
        f" {rotas_abaixo}\n\n[TABELA REAL - TOP ROTAS ABAIXO DA"
        f" ANTT]:\n{resumo_rotas_abaixo}"
    )

    instrucao = f"""Você é um Engenheiro de Logística Sênior e Consultor Estratégico da Natura.
        Sua missão principal é responder à pergunta de ouro: "Onde estão as minhas oportunidades de saving no frete pesado e qual a composição detalhada do Should Cost?"

        === REGRA CRÍTICA ANTI-ALUCINAÇÃO ===
        1. Responda a perguntas sobre rotas específicas, rankings ou desvios APENAS e EXCLUSIVAMENTE utilizando os dados contidos na [TABELA REAL - TOP ROTAS ABAIXO DA ANTT] acima.
        2. NUNCA invente ou adivinhe nomes de cidades, rotas ou transportadoras que não estejam presentes na base fornecida.

        === COMPOSIÇÃO OBRIGATÓRIA DO SHOULD COST ===
        Sempre que calcular ou simular o Should Cost de uma rota, apresente a COMPOSIÇÃO DETALHADA dos custos do frete em 3 blocos:
        1. CUSTOS VARIÁVEIS: Combustível (Diesel S10), Pneus/Desgaste de rodagem, Lubrificante e Manutenção.
        2. CUSTOS FIXOS DO ATIVO: Cavalo Mecânico e Baú/Carreta (Depreciação FIPE), IPVA, Licenciamento, Tacógrafo e Seguro.
        3. CUSTOS OPERACIONAIS E MARGEM: Pedágio, Ad Valorem e Margem do Transportador (10% a 15%).

        REGRA DO GERADOR: Se for solicitado gerar uma base de dados ou simulações, responda obrigatoriamente em formato de Tabela Markdown (separada por |).

        DADOS DE CONSULTA DA BASE NATURA: {contexto_ia_expandido}"""

    if "chat" not in st.session_state:
      configuracao_ia = {"temperature": 0.2}
      st.session_state.chat = genai.GenerativeModel(
          "gemini-3.1-flash-lite-preview",
          system_instruction=instrucao,
          generation_config=configuracao_ia,
      ).start_chat(history=[])
      st.session_state.msgs = []

    for m in st.session_state.msgs:
      with st.chat_message(m["role"]):
        st.markdown(m["content"])

    pergunta = st.chat_input(
        "Ex: Quais são as top 10 rotas abaixo da ANTT e sua composição?"
    )
    if pergunta:
      st.chat_message("user").markdown(pergunta)
      st.session_state.msgs.append({"role": "user", "content": pergunta})

      with st.chat_message("assistant"):
        try:
          with st.spinner("Analisando componentes de custo e mercado..."):
            res = st.session_state.chat.send_message(pergunta).text
          st.markdown(res)
          st.session_state.msgs.append({"role": "assistant", "content": res})
          salvar_historico_ia(pergunta, res)

          if "|" in res and "---" in res:
            linhas = res.split("\n")
            linhas_tabela = [l.strip() for l in linhas if "|" in l]

            linhas_validas = []
            for l in linhas_tabela:
              if "---" in l:
                continue
              cols = [c.strip() for c in l.strip("|").split("|")]
              if len(cols) > 1:
                linhas_validas.append(cols)

            if len(linhas_validas) > 1:
              with st.spinner(
                  "Carregando simulação direto no Google Sheets..."
              ):
                sucesso = salvar_simulacao_sheets(linhas_validas)
              if sucesso:
                st.success(
                    "✨ Nova base de simulação carregada com sucesso na sua"
                    " planilha consolidada!"
                )
                st.markdown(
                    "🔗 [Clique aqui para abrir a Planilha de"
                    f" Simulações]({LINK_PLANILHA_SIMULACOES})"
                )

        except Exception as e:
          st.error(f"Erro: {e}")
else:
  st.info("Planilha vazia ou carregando...")
