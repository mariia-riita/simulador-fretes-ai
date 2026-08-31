from datetime import datetime
import json
import time
import google.generativeai as genai
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import pydeck as pdk
import streamlit as st
import streamlit.components.v1 as components

# --- 1. CONFIGURAÇÃO DA PÁGINA E ESTILOS CUSTOMIZADOS ---
st.set_page_config(
    page_title="Should Cost IA - Natura", page_icon="🚛", layout="wide"
)

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
    
    /* Legenda do Mapa Logístico */
    .legenda-mapa {
        display: flex;
        align-items: center;
        gap: 18px;
        background-color: #1e1e1e;
        padding: 10px 18px;
        border-radius: 8px;
        margin-bottom: 12px;
        color: white;
        font-size: 13px;
    }
    .item-legenda { display: flex; align-items: center; gap: 6px; }
    .bola-legenda { width: 12px; height: 12px; border-radius: 50%; display: inline-block; }

    /* Ajuste de fonte para evitar corte de métricas */
    [data-testid="stMetricValue"] {
        font-size: 20px !important;
        font-weight: 700 !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 13px !important;
        white-space: normal !important;
        word-break: break-word !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- 2. CONSTANTES E CONEXÕES ---
CHAVE_API_GEMINI = st.secrets["GEMINI_API_KEY"]
LINK_PLANILHA = "https://docs.google.com/spreadsheets/d/12TSlwkvaklIWr4NBkAeM11vSfj9K_ycFZzqyGW9ImX0/edit?usp=sharing"
LINK_PLANILHA_SIMULACOES = "https://docs.google.com/spreadsheets/d/1o-cZbP27_Y0nUVvwdn2lT7q2AFja0MfLlexREF8f2Vc/edit?usp=sharing"
LINK_POWERBI_ANP = "https://app.powerbi.com/view?r=eyJrIjoiMGM0NDhhMTUtMjQwZi00N2RlLTk1M2UtYjkxZTlkNzM1YzE5IiwidCI6IjQ0OTlmNGZmLTI0YTYtNGI0Mi1iN2VmLTEyNGFmY2FkYzkxMyJ9"

genai.configure(api_key=CHAVE_API_GEMINI)


# --- 3. HELPER FUNCTIONS DE TRATAMENTO NUMÉRICO E BUSCA ---
def encontrar_coluna(df, palavras_chave, excluir=[]):
  """Encontra a coluna no DataFrame priorizando a ordem das palavras-chave fornecidas."""
  if df is None or len(df.columns) == 0:
    return None
  excluir_limpo = [x.upper() for x in excluir if x]
  for kw in palavras_chave:
    kw_upper = kw.upper()
    for col in df.columns:
      col_clean = str(col).upper().strip().replace("\n", " ").replace("\r", " ")
      if kw_upper in col_clean and not any(
          ex in col_clean for ex in excluir_limpo
      ):
        return col
  return None


def extrair_series(df, col_name):
  """Extrai com segurança uma pandas Series limpa, tratando colunas duplicadas no DataFrame."""
  if not col_name or df is None or col_name not in df.columns:
    return pd.Series("", index=df.index if df is not None else [0])
  val = df[col_name]
  if isinstance(val, pd.DataFrame):
    val = val.iloc[:, 0]
  return val.fillna("").astype(str).str.strip()


def limpar_numero_br_correto(valor):
  """Converte formatos numéricos BR (ex: '2.312,955' -> 2312.955) sem truncar milhares."""
  if pd.isna(valor):
    return 0.0
  v_str = str(valor).strip().upper().replace("\xa0", "").replace("\u202f", "")
  if v_str in ["", "NAN", "NULL", "NONE", "-", "#REF!", "#VALUE!", "#N/A"]:
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
  elif "." in v_str:
    parts = v_str.split(".")
    if len(parts) == 2 and len(parts[1]) == 3 and len(parts[0]) <= 3:
      v_str = v_str.replace(".", "")
    elif len(parts) > 2:
      v_str = v_str.replace(".", "")

  try:
    return float(v_str)
  except:
    return 0.0


def preparar_rotas_com_km_maps(df_rotas_in, df_kms_in):
  """Aplica o PROCX do De_Para_KMs do Google Maps sobre as Rotas Ativas de forma 100% segura."""
  if df_rotas_in is None or df_rotas_in.empty:
    return df_rotas_in, None, None

  df_rotas = df_rotas_in.copy()

  col_cod_o = encontrar_coluna(
      df_rotas,
      [
          "ZONA_DE_TRANSPORTE_ORIGEM",
          "CODIGO_ZONA_DE_TRANSPORTE_ORIGEM",
          "CODIGO_ORIGEM",
          "COD_ORIGEM",
      ],
      excluir=["DESCRICAO", "DESC", "NOME"],
  )
  col_cod_d = encontrar_coluna(
      df_rotas,
      [
          "ZONA_DE_TRANSPORTE_DESTINO",
          "CODIGO_ZONA_DE_TRANSPORTE_DESTINO",
          "CODIGO_DESTINO",
          "COD_DESTINO",
      ],
      excluir=["DESCRICAO", "DESC", "NOME"],
  )
  col_o = encontrar_coluna(
      df_rotas,
      [
          "DESCRICAO_ZONA_DE_TRANSPORTE_ORIGEM",
          "DESCRICAO_ORIGEM",
          "NOME_ORIGEM",
          "ORIGEM",
      ],
      excluir=["COD", "CODIGO", "ID"],
  )
  col_d = encontrar_coluna(
      df_rotas,
      [
          "DESCRICAO_ZONA_DE_TRANSPORTE_DESTINO",
          "DESCRICAO_DESTINO",
          "NOME_DESTINO",
          "DESTINO",
      ],
      excluir=["COD", "CODIGO", "ID"],
  )

  col_uf_o = encontrar_coluna(
      df_rotas,
      ["UF - ORIGEM", "UF_ORIGEM", "UF ORIGEM", "UF"],
      excluir=["DESTINO", "DEST", "1"],
  )
  col_uf_d = encontrar_coluna(
      df_rotas,
      [
          "UF - DESTINO",
          "UF_DESTINO",
          "UF DESTINO",
          "UF.1",
          "UF_DEST",
          "UF DEST",
          "UF",
      ],
      excluir=["ORIGEM", "ORIG"],
  )

  s_cod_o = extrair_series(df_rotas, col_cod_o)
  s_cod_d = extrair_series(df_rotas, col_cod_d)
  s_o = extrair_series(df_rotas, col_o)
  s_d = extrair_series(df_rotas, col_d)
  s_uf_o = extrair_series(df_rotas, col_uf_o)
  s_uf_d = extrair_series(df_rotas, col_uf_d)

  # PROCX com De_Para_KMs
  if df_kms_in is not None and not df_kms_in.empty:
    df_kms = df_kms_in.copy()
    col_km_maps = encontrar_coluna(df_kms, ["KM"])
    col_orig_maps = encontrar_coluna(df_kms, ["ORIGEM"])
    col_dest_maps = encontrar_coluna(df_kms, ["DESTINO"])

    if col_km_maps and col_orig_maps and col_dest_maps:
      s_km_maps = extrair_series(df_kms, col_km_maps)
      s_orig_maps = extrair_series(df_kms, col_orig_maps)
      s_dest_maps = extrair_series(df_kms, col_dest_maps)

      df_kms["KM_CLEAN"] = s_km_maps.apply(limpar_numero_br_correto)
      df_kms["CHAVE_LOOKUP"] = (
          s_orig_maps.str.upper().str.replace(" ", "")
          + s_dest_maps.str.upper().str.replace(" ", "")
      )
      km_dict = df_kms.groupby("CHAVE_LOOKUP")["KM_CLEAN"].first().to_dict()

      df_rotas["CHAVE_LOOKUP"] = (
          s_o.str.upper().str.replace(" ", "")
          + s_d.str.upper().str.replace(" ", "")
      )
      df_rotas["KM_GOOGLE_MAPS"] = df_rotas["CHAVE_LOOKUP"].map(km_dict)

  # Construção segura do nome da rota no seletor
  origem_str = (
      ("[" + s_cod_o + "] ").where(s_cod_o != "", "")
      + s_o
      + (" - " + s_uf_o).where(s_uf_o != "", "")
  )
  destino_str = (
      ("[" + s_cod_d + "] ").where(s_cod_d != "", "")
      + s_d
      + (" - " + s_uf_d).where(s_uf_d != "", "")
  )

  df_rotas["ROTA_NOME"] = origem_str + " ➔ " + destino_str

  return df_rotas, col_o, col_d


def limpar_coordenada(coord):
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


def sincronizar_sheets_auto(diesel_preco, df_rotas_calculadas):
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
      aba_param = planilha.worksheet("Parametros_Custos")
      aba_param.update("B2", [[diesel_preco]])
    except Exception:
      pass

    try:
      aba_rotas = planilha.worksheet("Rotas_Ativas")
      if "CUSTO_TOTAL" in df_rotas_calculadas.columns:
        novos_valores = [
            [v] for v in df_rotas_calculadas["CUSTO_TOTAL"].tolist()
        ]
        aba_rotas.update(f"N2:N{len(novos_valores)+1}", novos_valores)
    except Exception:
      pass

    return True
  except Exception as e:
    st.error(f"Erro ao sincronizar planilha online: {e}")
    return False


# --- 4. CARREGAMENTO EM TEMPO REAL DAS ABAS DO GOOGLE SHEETS ---
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

  try:
    fipe = planilha.worksheet("Apoio_FIPE").get_all_records()
  except:
    fipe = []

  try:
    antt = planilha.worksheet("Apoio_ANTT").get_all_records()
  except:
    antt = []

  try:
    kms = (
        planilha.worksheet("De_Para_KMs").get_all_records()
        if "De_Para_KMs" in [w.title for w in planilha.worksheets()]
        else planilha.worksheet("De_Para_KM").get_all_records()
    )
  except:
    kms = []

  try:
    param_custos = (
        planilha.worksheet("Parametros_Custos").get_all_records()
        if "Parametros_Custos" in [w.title for w in planilha.worksheets()]
        else planilha.worksheet("Apoio").get_all_records()
    )
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
          f"FIPE: {fipe}\nANTT: {antt}\nParâmetros de Custo Ativos:"
          f" {param_custos}"
      ),
      "tabela": df_rotas,
      "de_para_kms": pd.DataFrame(kms),
      "param_custos": pd.DataFrame(param_custos),
      "fipe": pd.DataFrame(fipe),
  }


# --- 5. INTERFACE DO USUÁRIO ---
st.title("🚛 Inteligência de Fretes - Natura")

with st.sidebar:
  st.header("⚙️ Controle")
  if st.button("🔄 Atualizar Painel de Dados"):
    with st.spinner("Sincronizando com a nuvem..."):
      st.cache_data.clear()
      st.success("Sincronizado!")
      time.sleep(1)
      st.rerun()

try:
  dados = ler_base_sheets()
  contexto_ia = dados["contexto"]
  df_rotas_bruta = dados["tabela"].copy()
  df_kms_bruta = dados["de_para_kms"].copy()
  df_param_custos = dados["param_custos"]
  df_fipe = dados["fipe"]
except Exception as e:
  st.error(f"Erro ao conectar com o Google Sheets: {e}")
  df_rotas_bruta = pd.DataFrame()
  df_kms_bruta = pd.DataFrame()
  df_param_custos = pd.DataFrame()
  df_fipe = pd.DataFrame()

# --- RADAR DO DIESEL E AUTO-SYNC NA SIDEBAR ---
with st.sidebar:
  st.write("---")
  st.header("⛽ Radar do Diesel S10")

  diesel_medio_base = 5.95
  diesel_medio_atual = st.number_input(
      "Preço Médio Nacional (R$/L):",
      min_value=4.00,
      max_value=12.00,
      value=diesel_medio_base,
      step=0.05,
      help="Altera automaticamente o pilar de combustível em tempo real.",
  )

  st.metric(
      label="Diesel S10 no Simulador", value=f"R$ {diesel_medio_atual:.2f} /L"
  )
  st.caption(
      "💡 Para variação semanal oficial da ANP, acesse a aba **⛽ Painel ANP"
      " Oficial**."
  )

  st.write("---")
  st.header("🔄 Gravação em Nuvem")
  if st.button("💾 Gravar Novos Custos no Google Sheets"):
    with st.spinner("Atualizando planilha oficial online..."):
      if sincronizar_sheets_auto(diesel_medio_atual, df_rotas_bruta):
        st.success("Planilha no Google Sheets gravada com sucesso!")
        st.cache_data.clear()

if not df_rotas_bruta.empty:
  df_rotas = df_rotas_bruta.copy()
  df_rotas.columns = (
      df_rotas.columns.astype(str)
      .str.replace("\n", "")
      .str.replace("\r", "")
      .str.strip()
      .str.upper()
  )

  if not df_kms_bruta.empty:
    df_kms_bruta.columns = (
        df_kms_bruta.columns.astype(str)
        .str.replace("\n", "")
        .str.replace("\r", "")
        .str.strip()
        .str.upper()
    )

  # Formatação e PROCX dos KMs do Google Maps de forma 100% segura
  df_rotas, col_o_global, col_d_global = preparar_rotas_com_km_maps(
      df_rotas, df_kms_bruta
  )

  col_base = encontrar_coluna(df_rotas, ["CUSTO", "BASE"])
  col_contrato = encontrar_coluna(df_rotas, ["CONTRATO"])
  col_frete = encontrar_coluna(df_rotas, ["FRETE", "CONS"])
  col_pedagio = encontrar_coluna(df_rotas, ["PEDAGIO", "PEDÁGIO"])
  col_vol = encontrar_coluna(df_rotas, ["VOL", "VOLUME"])
  col_status = encontrar_coluna(df_rotas, ["STATUS", "SITUACAO", "SITUAÇÃO"])

  base = (
      extrair_series(df_rotas, col_base).apply(limpar_numero_br_correto)
      if col_base
      else pd.Series([0.0] * len(df_rotas))
  )
  contrato = (
      extrair_series(df_rotas, col_contrato).apply(limpar_numero_br_correto)
      if col_contrato
      else pd.Series([0.0] * len(df_rotas))
  )
  frete_considerado = (
      extrair_series(df_rotas, col_frete).apply(limpar_numero_br_correto)
      if col_frete
      else pd.Series([0.0] * len(df_rotas))
  )
  pedagio = (
      extrair_series(df_rotas, col_pedagio).apply(limpar_numero_br_correto)
      if col_pedagio
      else pd.Series([0.0] * len(df_rotas))
  )
  volume = (
      extrair_series(df_rotas, col_vol).apply(limpar_numero_br_correto)
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

  # CÁLCULO PRECISÃO DO STATUS ANTT (DENTRO / ABAIXO DA ANTT)
  rotas_dentro = 0
  rotas_abaixo = 0

  if col_status:
    s_status = extrair_series(df_rotas, col_status).str.upper()
    rotas_dentro = int(len(df_rotas[s_status.str.contains("DENTRO", na=False)]))
    rotas_abaixo = int(len(df_rotas[s_status.str.contains("ABAIXO", na=False)]))

  if (rotas_dentro == 0 and rotas_abaixo == 0) and not df_rotas.empty:
    col_dif_r = encontrar_coluna(
        df_rotas, ["DIF R$", "DIF R", "DIF_R$", "DIFERENCA", "DIF"]
    )
    col_frete_nat = encontrar_coluna(
        df_rotas,
        [
            "FRETE NATURA",
            "FRETE_NATURA",
            "CUSTO_TOTAL",
            "FRETE CONSIDERADO",
            "CUSTO BASE",
            "CUSTO_BASE",
        ],
    )
    col_frete_min = encontrar_coluna(
        df_rotas,
        [
            "FRETE MINIMO",
            "FRETE MÍNIMO",
            "FRETE_MINIMO",
            "FRETE_MÍNIMO",
            "ANTT",
        ],
    )

    if col_dif_r:
      s_dif = extrair_series(df_rotas, col_dif_r).apply(
          limpar_numero_br_correto
      )
      raw_dif = extrair_series(df_rotas, col_dif_r)
      s_validas = raw_dif.apply(
          lambda x: (
              pd.notna(x)
              and str(x).strip()
              not in ["", "nan", "None", "#REF!", "#N/A", "#VALUE!"]
          )
      )
      rotas_dentro = int((s_dif[s_validas] >= 0).sum())
      rotas_abaixo = int((s_dif[s_validas] < 0).sum())

      df_rotas["STATUS"] = "DENTRO DA ANTT"
      df_rotas.loc[s_validas & (s_dif < 0), "STATUS"] = "ABAIXO DA ANTT"
      col_status = "STATUS"
    elif col_frete_nat and col_frete_min:
      s_nat = extrair_series(df_rotas, col_frete_nat).apply(
          limpar_numero_br_correto
      )
      s_min = extrair_series(df_rotas, col_frete_min).apply(
          limpar_numero_br_correto
      )
      s_validas = (s_min > 0) & (s_nat > 0)
      rotas_dentro = int(((s_nat >= s_min) & s_validas).sum())
      rotas_abaixo = int(((s_nat < s_min) & s_validas).sum())

      df_rotas["STATUS"] = "DENTRO DA ANTT"
      df_rotas.loc[s_validas & (s_nat < s_min), "STATUS"] = "ABAIXO DA ANTT"
      col_status = "STATUS"

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
      help="Tarifas maiores que o piso mínimo.",
  )
  col5.metric(
      "🔻 Abaixo da ANTT",
      f"{rotas_abaixo} rotas",
      help="Tarifas abaixo do piso regulamentar por lei.",
  )

  st.divider()

  col_grafico, col_chat = st.columns([1.3, 1])

  with col_grafico:
    (
        aba_barras,
        aba_mapa,
        aba_should_cost,
        aba_anp_pbi,
    ) = st.tabs([
        "📊 Custo por CD",
        "🗺️ Mapa de Densidade",
        "📋 Composição Should Cost",
        "⛽ Painel ANP Oficial",
    ])

    with aba_barras:
      st.markdown("### 📊 Custo por CD de Origem")
      col_origem = col_o_global or encontrar_coluna(
          df_rotas, ["DESCRICAO", "NOME", "ORIGEM", "ZONA_DE_TRANSPORTE_ORIGEM"]
      )

      if col_origem:
        s_origem_cat = extrair_series(df_rotas, col_origem).str.upper()
        df_rotas["CD_ORIGEM_CAT"] = s_origem_cat
        df_chart = (
            df_rotas.groupby("CD_ORIGEM_CAT")["Custo_Total_Ponderado"]
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
                  "CD_ORIGEM_CAT": "CD de Origem",
                  "Custo_Total_Ponderado": "Custo R$",
              }
          )
          st.bar_chart(
              df_chart.set_index("CD de Origem"),
              use_container_width=True,
              color="#FF6600",
          )
        else:
          st.warning("⚠️ Os valores calculados vieram zerados.")
      else:
        st.error("🚨 Coluna de Origem não encontrada!")

    # 🗺️ MAPA LOGÍSTICO DENSIDADE + ARCOS
    with aba_mapa:
      col_lat_o = encontrar_coluna(df_rotas, ["LAT"], excluir=["DEST"])
      col_lon_o = encontrar_coluna(df_rotas, ["LON"], excluir=["DEST"])
      col_lat_d = encontrar_coluna(df_rotas, ["LAT"], excluir=["ORIG"])
      col_lon_d = encontrar_coluna(df_rotas, ["LON"], excluir=["ORIG"])

      if col_lat_o and col_lon_o and col_lat_d and col_lon_d:
        df_rotas["lat_origem"] = extrair_series(
            df_rotas, col_lat_o
        ).apply(limpar_coordenada)
        df_rotas["lon_origem"] = extrair_series(
            df_rotas, col_lon_o
        ).apply(limpar_coordenada)
        df_rotas["lat_destino"] = extrair_series(
            df_rotas, col_lat_d
        ).apply(limpar_coordenada)
        df_rotas["lon_destino"] = extrair_series(
            df_rotas, col_lon_d
        ).apply(limpar_coordenada)

        df_mapa = df_rotas.dropna(
            subset=["lat_origem", "lon_origem", "lat_destino", "lon_destino"]
        ).copy()

        if not df_mapa.empty:
          col_origem_nome = col_o_global or encontrar_coluna(
              df_mapa,
              ["DESCRICAO", "NOME", "ORIGEM", "ZONA_DE_TRANSPORTE_ORIGEM"],
          )
          if col_origem_nome:
            s_orig_mapa = extrair_series(df_mapa, col_origem_nome)
            contagem_origem = s_orig_mapa.value_counts().to_dict()
            df_mapa["densidade_origem"] = (
                s_orig_mapa.map(contagem_origem).fillna(1)
            )
          else:
            df_mapa["densidade_origem"] = 1

          max_dens = df_mapa["densidade_origem"].max()

          def gerar_cor_densidade(qtd):
            ratio = qtd / max_dens if max_dens > 0 else 0
            if ratio > 0.60:
              return [230, 25, 25, 230]
            elif ratio > 0.25:
              return [255, 130, 0, 200]
            else:
              return [255, 215, 0, 180]

          df_mapa["cor_origem"] = df_mapa["densidade_origem"].apply(
              gerar_cor_densidade
          )

          st.markdown(
              """
              <div class="legenda-mapa">
                  <span style="font-weight:600; color:#FF9900;">📍 Densidade de Origem (Volume):</span>
                  <div class="item-legenda"><span class="bola-legenda" style="background:#FFD700;"></span> Baixo Volume</div>
                  <div class="item-legenda"><span class="bola-legenda" style="background:#FF8200;"></span> Médio Volume</div>
                  <div class="item-legenda"><span class="bola-legenda" style="background:#E61919;"></span> Alto Volume (Gargalo)</div>
                  <div class="item-legenda"><span class="bola-legenda" style="background:#00C8FF;"></span> Destino Ciano</div>
              </div>
              """,
              unsafe_allow_html=True,
          )

          camada_origens = pdk.Layer(
              "ScatterplotLayer",
              data=df_mapa,
              get_position=["lon_origem", "lat_origem"],
              get_color="cor_origem",
              get_radius=18000,
              pickable=True,
          )
          camada_destinos = pdk.Layer(
              "ScatterplotLayer",
              data=df_mapa,
              get_position=["lon_destino", "lat_destino"],
              get_color=[0, 200, 255, 200],
              get_radius=12000,
              pickable=True,
          )
          camada_arcos = pdk.Layer(
              "ArcLayer",
              data=df_mapa,
              get_source_position=["lon_origem", "lat_origem"],
              get_target_position=["lon_destino", "lat_destino"],
              get_source_color="cor_origem",
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
          st.warning("⚠️ Sem coordenadas válidas.")
      else:
        st.error("⚠️ Colunas de Latitude/Longitude não encontradas!")

    # 📋 ABA: SHOULD COST DINÂMICO RECALCULADO POR ROTA (PROCX COM DE_PARA_KMS)
    with aba_should_cost:
      st.markdown("### 📋 SIMULADOR DE FRETES (Metodologia Oficial)")
      st.caption(
          "Cálculo exato de frete por viagem, ANTT, horas operacionais e"
          " composição com KMs do Google Maps."
      )

      col_km_fallback = encontrar_coluna(
          df_rotas,
          ["KM'S CONFERIDOS", "DISTÂNCIA", "DISTANCIA", "KM"],
          excluir=["PONDE", "TOTAL", "MÊS", "MES", "SPEND"],
      )
      col_veic = encontrar_coluna(
          df_rotas, ["VEÍCULO", "VEICULO", "PERFIL", "EQUIPAMENTO", "TIPO"]
      )

      if "ROTA_NOME" in df_rotas.columns:
        s_rotas_nomes = extrair_series(df_rotas, "ROTA_NOME")
        lista_rotas = sorted(s_rotas_nomes[s_rotas_nomes != ""].unique().tolist())

        rota_selecionada = st.selectbox(
            "🎯 Selecione ou digite a Rota (Código, Cidade ou UF):",
            lista_rotas,
            key="sb_should_cost_rota",
        )

        df_foco = df_rotas[df_rotas["ROTA_NOME"] == rota_selecionada]

        if not df_foco.empty:
          df_rota_foco = df_foco.iloc[0]

          # Prioriza o KM do De_Para_KMs (Google Maps)
          km_maps = df_rota_foco.get("KM_GOOGLE_MAPS", None)
          if (
              pd.notna(km_maps)
              and isinstance(km_maps, (int, float))
              and km_maps > 0
          ):
            km_rota = float(km_maps)
          else:
            km_val = (
                limpar_numero_br_correto(df_rota_foco.get(col_km_fallback, 0))
                if col_km_fallback
                else 0.0
            )
            km_rota = km_val if km_val > 0 else 2310.0

          perfil_veic_str = (
              str(df_rota_foco.get(col_veic, "CARRETA")).upper()
              if col_veic
              else "CARRETA"
          )

          # MOTOR DE CÁLCULO FIEL À PLANILHA OFICIAL
          factor_km = km_rota / 2310.0
          velocidade_media = 65.0  # km/h
          tempo_transito_h = km_rota / velocidade_media
          tempo_carga_h, tempo_descarga_h = 12.0, 12.0
          tempo_total_h = (tempo_transito_h * 2.0) + tempo_carga_h + tempo_descarga_h
          dias_operacao = tempo_total_h / 10.0  # 10h jornada por dia

          # COMPOSIÇÃO DE CUSTOS MENSAIS DO ATIVO DEDICADO
          veiculo_mes = 39764.20 * factor_km
          mao_obra_mes = 102837.00
          docs_mes = 322.70
          seguros_mes = 4569.52
          manutencao_mes = 25780.00 * factor_km
          combustivel_mes = (
              130617.00 * (diesel_medio_atual / 5.95) * factor_km
          )
          lub_lav_mes = 4874.00 * factor_km
          pneu_mes = 17309.00 * factor_km

          subtotal_mes = (
              veiculo_mes
              + mao_obra_mes
              + docs_mes
              + seguros_mes
              + manutencao_mes
              + combustivel_mes
              + lub_lav_mes
              + pneu_mes
          )
          lucro_mes = subtotal_mes * 0.10
          piscofins_mes = (subtotal_mes + lucro_mes) * (0.0925 / (1.0 - 0.0925))

          custo_total_mes = subtotal_mes + lucro_mes + piscofins_mes
          viagens_mes = 22.32  # Viagens/mês base

          frete_simulador = custo_total_mes / viagens_mes
          frete_simulador_por_km = (
              frete_simulador / km_rota if km_rota > 0 else 0
          )

          frete_antt = 18843.57 * factor_km
          frete_antt_por_km = frete_antt / km_rota if km_rota > 0 else 0
          dif_antt_pct = (
              ((frete_simulador - frete_antt) / frete_antt) * 100.0
              if frete_antt > 0
              else 0.0
          )

          # EXIBIÇÃO IDÊNTICA AO PAINEL OFICIAL
          st.write("---")
          c1, c2, c3 = st.columns([1.2, 1, 1])
          c1.metric(
              "Frete Simulador",
              f"R$ {frete_simulador:,.2f}".replace(",", "X")
              .replace(".", ",")
              .replace("X", "."),
              delta=f"R$ {frete_simulador_por_km:.2f} / km",
          )
          c2.metric(
              "Frete ANTT",
              f"R$ {frete_antt:,.2f}".replace(",", "X")
              .replace(".", ",")
              .replace("X", "."),
              delta=f"{dif_antt_pct:.0f}% vs Simulador",
          )
          c3.metric("Dias Total de Operação", f"{dias_operacao:.1f} dias")

          st.write("")
          c4, c5, c6 = st.columns(3)
          c4.metric(
              "Distância da Rota (Google Maps)",
              f"{km_rota:,.1f} km".replace(",", "X")
              .replace(".", ",")
              .replace("X", "."),
              delta="Percurso One-Way",
          )
          c5.metric("Tempo Total (H)", f"{tempo_total_h:.1f} h")
          c6.metric("Tempo Trânsito (H)", f"{tempo_transito_h:.1f} h")

          st.write("---")
          st.markdown("#### 📊 Composição de Frete (Valores Mensais e %)")

          pilares_oficiais = [
              {
                  "Item": "Veículo",
                  "Valor Mensal (R$)": veiculo_mes,
                  "%": veiculo_mes / custo_total_mes,
              },
              {
                  "Item": "Mão de Obra",
                  "Valor Mensal (R$)": mao_obra_mes,
                  "%": mao_obra_mes / custo_total_mes,
              },
              {
                  "Item": "Documentos",
                  "Valor Mensal (R$)": docs_mes,
                  "%": docs_mes / custo_total_mes,
              },
              {
                  "Item": "Seguros",
                  "Valor Mensal (R$)": seguros_mes,
                  "%": seguros_mes / custo_total_mes,
              },
              {
                  "Item": "Manutenção",
                  "Valor Mensal (R$)": manutencao_mes,
                  "%": manutencao_mes / custo_total_mes,
              },
              {
                  "Item": "Combustível",
                  "Valor Mensal (R$)": combustivel_mes,
                  "%": combustivel_mes / custo_total_mes,
              },
              {
                  "Item": "Lubrificante e lavagem",
                  "Valor Mensal (R$)": lub_lav_mes,
                  "%": lub_lav_mes / custo_total_mes,
              },
              {
                  "Item": "Pneu",
                  "Valor Mensal (R$)": pneu_mes,
                  "%": pneu_mes / custo_total_mes,
              },
              {
                  "Item": "Lucro",
                  "Valor Mensal (R$)": lucro_mes,
                  "%": lucro_mes / custo_total_mes,
              },
              {
                  "Item": "PIS/Cofins",
                  "Valor Mensal (R$)": piscofins_mes,
                  "%": piscofins_mes / custo_total_mes,
              },
          ]

          df_comp = pd.DataFrame(pilares_oficiais)
          df_comp["% Representação"] = df_comp["%"].apply(
              lambda x: f"{x*100:.0f}%"
          )
          df_comp["R$ Mensal"] = df_comp["Valor Mensal (R$)"].apply(
              lambda x: f"R$ {x:,.0f}".replace(",", ".")
          )

          col_tabela, col_pie = st.columns([1, 1])

          with col_tabela:
            st.dataframe(
                df_comp[["Item", "R$ Mensal", "% Representação"]],
                use_container_width=True,
                hide_index=True,
            )

          with col_pie:
            custo_fixo_cat = veiculo_mes + docs_mes + seguros_mes
            custo_var_cat = (
                manutencao_mes + combustivel_mes + lub_lav_mes + pneu_mes
            )
            custo_mo_cat = mao_obra_mes

            df_macro = pd.DataFrame({
                "Categoria": ["Fixo", "Variável", "Mão de Obra"],
                "Valor": [custo_fixo_cat, custo_var_cat, custo_mo_cat],
            })
            st.bar_chart(df_macro.set_index("Categoria"), color="#FF6600")

      else:
        st.info("Aguardando rotas da planilha...")

    # 🖥️ ABA DO POWERBI DA ANP
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

      html_pbi = f'<iframe title="Painel ANP" width="100%" height="650" src="{LINK_POWERBI_ANP}" frameborder="0" allowFullScreen="true" style="border:0; border-radius:10px;"></iframe>'
      components.html(html_pbi, height=670)

  # --- PAINEL DO CHAT IA ---
  with col_chat:
    st.subheader("🤖 Agente Estratégico de Fretes")

    resumo_rotas_abaixo = ""
    if not df_rotas.empty and col_status:
      s_status_chat = extrair_series(df_rotas, col_status).str.lower()
      df_temp = df_rotas.copy()
      df_temp["STATUS_CLEAN"] = s_status_chat
      df_abaixo_real = df_temp[
          df_temp["STATUS_CLEAN"].str.contains("abaixo", na=False)
      ].copy()

      col_dif_antt = encontrar_coluna(
          df_abaixo_real, ["DIF R$", "DIF ANTT", "DIF R$"]
      )

      if col_dif_antt:
        s_dif_antt = extrair_series(df_abaixo_real, col_dif_antt)
        df_abaixo_real["DIF_R$_NUM"] = s_dif_antt.apply(
            limpar_numero_br_correto
        )
        top_15_abaixo = df_abaixo_real.sort_values(
            by="DIF_R$_NUM", ascending=True
        ).head(15)

        cols_prompt = [
            col
            for col in df_abaixo_real.columns
            if any(
                k in col
                for k in [
                    "TRANSPORTADORA",
                    "ORIGEM",
                    "DESTINO",
                    "EQUIPAMENTO",
                    "FRETE",
                    "ANTT",
                    "DIF",
                ]
            )
        ]
        if cols_prompt:
          resumo_rotas_abaixo = top_15_abaixo[cols_prompt[:8]].to_string(
              index=False
          )

    contexto_ia_expandido = (
        contexto_ia
        + f"\n\n[MÉTRICAS DA OPERAÇÃO REAL NATURA]:\n- Total de Rotas na Tabela:"
        f" {len(df_rotas)}\n- Rotas com frete DENTRO do Mínimo ANTT:"
        f" {rotas_dentro}\n- Rotas com frete ABAIXO do Mínimo ANTT:"
        f" {rotas_abaixo}\n\n[TABELA REAL - TOP ROTAS ABAIXO DA"
        f" ANTT]:\n{resumo_rotas_abaixo}\n"
        f"O Diesel considerado atualmente na simulação é de R$ {diesel_medio_atual:.2f}/L."
    )

    instrucao = f"""Você é um Engenheiro de Logística Sênior e Especialista em Should Cost da Natura.
        Sua função é apresentar o Should Cost fiel à planilha oficial do Google Sheets.

        === ESTRUTURA PADRÃO DO SHOULD COST (10 PILARES OFICIAIS) ===
        Sempre que for solicitado o Should Cost ou a composição de custos de uma rota, apresente a tabela e o detalhamento seguindo os 10 componentes da planilha:

        1. VEÍCULO: Depreciação do Cavalo Mecânico + Implemento/Baú + Remuneração do Capital (Juros)
        2. MÃO DE OBRA: Salário base do motorista + Encargos Sociais/Trabalhistas (75%) + Benefícios + Diárias + Horas Extras
        3. DOCUMENTOS: IPVA + Licenciamento + Tacógrafo
        4. SEGUROS: Seguro do Veículo + Seguro do Implemento
        5. MANUTENÇÃO: Custo de manutenção preventiva/corretiva por Km rodado
        6. COMBUSTÍVEL: Consumo de Diesel S10 (considerando R$ {diesel_medio_atual:.2f}/L) + ARLA 32
        7. LUBRIFICANTE E LAVAGEM: Custo por Km de troca de óleo de cárter + Lavagens do veículo
        8. PNEU: Desgaste e durabilidade de pneus novos (Dianteiro/Traseiro) + Recapagens
        9. LUCRO: Margem de Lucro do Transportador (10%)
        10. PIS / COFINS: Impostos incidentes sobre o frete (9,25%)

        === REGRAS DE APRESENTAÇÃO ===
        - Monte uma TABELA DE RESUMO com o valor em R$ e a % de representatividade de cada um dos 10 pilares em relação ao custo total da viagem.
        - Utilize apenas os parâmetros cadastrados nas abas Apoio_FIPE, Parametros_Custos e Rotas_Ativas.
        - Para consultas de rotas específicas, utilize os dados de [TABELA REAL - TOP ROTAS ABAIXO DA ANTT].
        - Se o usuário pedir para gerar uma base ou simulação em lote, responda em formato de Tabela Markdown (separada por |).

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
        "Ex: Monte o Should Cost detalhado da rota Benevides x Uberlândia com"
        " os 10 pilares e a quantidade de viagens por mês."
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
                    " planilha!"
                )
                st.markdown(
                    "🔗 [Clique aqui para abrir a Planilha de"
                    f" Simulações]({LINK_PLANILHA_SIMULACOES})"
                )

        except Exception as e:
          st.error(f"Erro: {e}")
else:
  st.info("Planilha vazia ou carregando...")
