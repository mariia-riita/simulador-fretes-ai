import streamlit as st
import google.generativeai as genai
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. CONFIGURAÇÕES INICIAIS (COLE AQUI SUAS CHAVES) ---
CHAVE_API_GEMINI = st.secrets["GEMINI_API_KEY"]
LINK_PLANILHA = "https://docs.google.com/spreadsheets/d/1fx4Wo57AStcBe4CPlsNU7NvAQLw3rnApXJGmPwT58uI/edit?usp=sharing"

genai.configure(api_key=CHAVE_API_GEMINI)

st.set_page_config(page_title="Should Cost - IA", page_icon="🚚", layout="centered")
st.title("🚚 Simulador de Fretes com IA")
st.markdown("Assistente inteligente alimentado pelo **Google Gemini** e integrado ao seu **Google Sheets**.")
st.divider()

# --- 2. LENDO DADOS DA PLANILHA PARA ENSINAR A IA ---
@st.cache_data(ttl=600) # O site guarda a planilha na memória por 10 min pra ficar rápido
def ler_base_sheets():
    escopos = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    credenciais = ServiceAccountCredentials.from_json_keyfile_name('should-cost-automacao-7908fa6b25d5.json', escopos)
    cliente = gspread.authorize(credenciais)
    planilha = cliente.open_by_url(LINK_PLANILHA)
    aba = planilha.worksheet("Base_IA")
    return aba.get_all_records()

# Tenta ler os dados da planilha
try:
    dados_operacionais = ler_base_sheets()
    contexto_planilha = str(dados_operacionais)
except Exception as e:
    contexto_planilha = "Erro ao ler a planilha. Assuma Diesel a R$ 5,80 e Caminhão a R$ 750.000."

# --- 3. CONFIGURANDO A MENTE DO GEMINI ---
# Aqui ensinamos como ele deve se comportar e passamos os valores do Sheets pra ele!
instrucao_sistema = f"""
Você é um Engenheiro de Logística Sênior da Natura, especialista em cálculo de 'Should Cost' de fretes rodoviários.
Sua missão é responder às perguntas do usuário cruzando os dados operacionais atualizados.

AQUI ESTÃO OS DADOS OPERACIONAIS ATUAIS RETIRADOS DA PLANILHA DA EMPRESA:
{contexto_planilha}

Regras:
1. Sempre use os dados acima para basear suas respostas matemáticas.
2. Seja profissional, direto e analítico.
3. Se o usuário perguntar o custo de uma rota, faça o cálculo matemático considerando o diesel, depreciação do ativo (caminhão) e lucro da transportadora (assuma 10%). Mostre a memória de cálculo.
"""

modelo = genai.GenerativeModel(
    model_name="gemini-3.1-flash-lite-preview",
    system_instruction=instrucao_sistema
)

# --- 4. MEMÓRIA DO CHAT ---
if "mensagens" not in st.session_state:
    st.session_state.mensagens = []
    # Inicia o chat do Gemini internamente
    st.session_state.chat_gemini = modelo.start_chat(history=[])

for msg in st.session_state.mensagens:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- 5. A INTERFACE DO CHAT ---
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
        
        # O envio real da pergunta para o Gemini
        try:
            resposta_gemini = st.session_state.chat_gemini.send_message(pergunta)
            texto_final = resposta_gemini.text
            resposta_placeholder.markdown(texto_final)
            
            # Salva na memória
            st.session_state.mensagens.append({"role": "assistant", "content": texto_final})
        except Exception as e:
            resposta_placeholder.markdown(f"**Erro na IA:** Verifique se a sua Chave de API está correta. Detalhes: {e}")
