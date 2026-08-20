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

# --- 1. CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Should Cost IA - Natura", page_icon="🚛", layout="wide"
)

# --- 1.1 FONTE POPPINS & ESTILOS CUSTOMIZADOS ---
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

    /* Legenda do Mapa */
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
    .item-legenda {
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .bola-legenda {
        width: 12px;
        height: 12px;
        border-radius: 50%;
        display: inline-block;
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


# --- 3. MÁQUINAS DE LIMPEZA E SALVAMENTO ---
def limpar_numero_br(valor):
  """Converte valores financeiros para float"""
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
  """Recupera coordenadas mesmo se formatadas incorretamente"""
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
          f"FIPE (Preço Veículos): {fipe}\nANTT (Piso Mínimo): {antt}\nParâmetros"
          f" Custos Fixos & Impostos: {param_custos}"
      ),
      "tabela": df_rotas,
  }


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
  st.error(f"Erro de conexão real com o Google Sheets: {e}")
  df_rotas = pd.DataFrame()

# --- RADAR DO DIESEL NA SIDEBAR ---
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
      help=(
          "Consulte o valor exato na aba '⛽ Painel ANP Oficial' do dashboard e"
          " ajuste aqui se necessário."
      ),
  )

  st.metric(
      label="Diesel S10 Utilizado nos Cálculos",
      value=f"R$ {diesel_medio_atual:.2f} /L",
  )

  st.caption(
      "💡 **Dica:** Para verificar a variação estadual semanal, consulte a aba"
      " **⛽ Painel ANP Oficial**."
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
          st.warning("⚠️ Os valores calculados vieram zerados.")
      else:
        st.error(
            "🚨 A coluna 'DESCRICAO_ZONA_DE_TRANSPORTE_ORIGEM' não foi"
            " encontrada!"
        )

    # 🗺️ ABA DO MAPA COM DENSIDADE, ARCOS E DESTINO CIANO
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
        ).copy()

        if not df_mapa.empty:
          col_origem_nome = "DESCRICAO_ZONA_DE_TRANSPORTE_ORIGEM"
          if col_origem_nome in df_mapa.columns:
            contagem_origem = (
                df_mapa[col_origem_nome].value_counts().to_dict()
            )
            df_mapa["densidade_origem"] = (
                df_mapa[col_origem_nome].map(contagem_origem).fillna(1)
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

    # 📋 NOVA ABA: SIMULADOR DE COMPOSIÇÃO DOS 10 PILARES DO SHOULD COST
    with aba_should_cost:
      st.markdown("### 📋 Simulador do Should Cost (10 Pilares)")
      st.caption(
          "Selecione uma rota para visualizar a decomposição oficial do frete"
          " idêntica à planilha do simulador."
      )

      col_o = "DESCRICAO_ZONA_DE_TRANSPORTE_ORIGEM"
      col_d = "DESCRICAO_ZONA_DE_TRANSPORTE_DESTINO"

      if col_o in df_rotas.columns and col_d in df_rotas.columns:
        df_rotas["ROTA_NOME"] = (
            df_rotas[col_o].astype(str) + " ➔ " + df_rotas[col_d].astype(str)
        )
        lista_rotas = sorted(df_rotas["ROTA_NOME"].unique().tolist())

        rota_selecionada = st.selectbox("🎯 Escolha a Rota:", lista_rotas)

        df_rota_foco = df_rotas[df_rotas["ROTA_NOME"] == rota_selecionada].iloc[
            0
        ]
        custo_total_rota = float(df_rota_foco.get("CUSTO_TOTAL", 15000.0))
        if custo_total_rota <= 0:
          custo_total_rota = 18000.0

        # Percentuais Médios dos 10 Pilares (Baseados no Simulador Oficial)
        pilares_pct = {
            "1. Veículo & Implemento (Capital/Depreciação)": 0.10,
            "2. Mão de Obra (Salário, Encargos 75%, Diárias)": 0.26,
            "3. Documentos (IPVA, Licenciamento, Tacógrafo)": 0.005,
            "4. Seguros (Veículo e Implemento)": 0.012,
            "5. Manutenção Preventiva/Corretiva": 0.065,
            "6. Combustível (Diesel S10 + ARLA 32)": 0.33,
            "7. Lubrificante e Lavagem": 0.012,
            "8. Pneus & Recapagem": 0.044,
            "9. Margem de Lucro do Transportador": 0.08,
            "10. Tributos (PIS / COFINS)": 0.092,
        }

        # Criação do DataFrame com os 10 Pilares
        dados_pilares = []
        for pilar, pct in pilares_pct.items():
          valor_pilar = custo_total_rota * pct
          dados_pilares.append({
              "Componente do Cost Driver": pilar,
              "Participação (%)": f"{pct*100:.1f}%",
              "Valor Estimado (R$)": f"R$ {valor_pilar:,.2f}".replace(
                  ",", "X"
              )
              .replace(".", ",")
              .replace("X", "."),
              "Valor_Num": valor_pilar,
          })

        df_pilares_display = pd.DataFrame(dados_pilares)

        # Exibição de Métricas da Rota
        m1, m2, m3 = st.columns(3)
        m1.metric("Custo Estimado da Viagem", f"R$ {custo_total_rota:,.2f}")
        m2.metric(
            "Combustível Considerado", f"R$ {custo_total_rota*0.33:,.2f} (33%)"
        )
        m3.metric("Mão de Obra & Diárias", f"R$ {custo_total_rota*0.26:,.2f}")

        st.write("---")
        st.markdown("#### 📊 Decomposição Estruturada dos Custos")

        # Exibe Tabela de Composição
        st.dataframe(
            df_pilares_display[[
                "Componente do Cost Driver",
                "Participação (%)",
                "Valor Estimado (R$)",
            ]],
            use_container_width=True,
            hide_index=True,
        )

        # Gráfico de Barras dos Pilares
        df_pilares_chart = df_pilares_display.set_index(
            "Componente do Cost Driver"
        )[["Valor_Num"]]
        df_pilares_chart.columns = ["R$ Est."]
        st.bar_chart(df_pilares_chart, color="#FF6600")

      else:
        st.info("Colunas de Origem e Destino necessárias para simulação.")

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

      html_pbi = f"""
      <iframe title="Painel ANP" width="100%" height="650" src="{LINK_POWERBI_ANP}" frameborder="0" allowFullScreen="true" style="border:0; border-radius:10px;"></iframe>
      """
      components.html(html_pbi, height=670)

  # --- PAINEL DO CHAT IA ---
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
        f" ANTT]:\n{resumo_rotas_abaixo}\n"
        f"O Diesel considerado atualmente na simulação é de R$ {diesel_medio_atual:.2f}/L."
    )

    instrucao = f"""Você é um Engenheiro de Logística Sênior e Especialista em Should Cost da Natura.
        Sua função é apresentar o Should Cost fiel à planilha oficial (Simulador_Frete_Pesado_2026).

        === ESTRUTURA PADRÃO DO SHOULD COST (10 PILARES OFICIAIS) ===
        Sempre que for solicitado o Should Cost ou a composição de custos de uma rota, apresente a tabela e o detalhamento seguindo rigorosamente os 10 componentes da planilha:

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
        - Utilize apenas os parâmetros cadastrados nas abas Apoio, Base_Cálculo e Parametros_Custos.
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
        "Ex: Monte o Should Cost detalhado da rota Itupeva x Murici com os 10"
        " pilares."
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
