from datetime import date, datetime
import hashlib
import json
import os
import re
import cv2
from fpdf import FPDF
import numpy as np
from numpy import asarray
import pandas as pd
from PIL import Image
import requests
import streamlit as st
from sqlalchemy import create_engine, text


# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Multi-Cartão Terapêutico - Técnico de Campo",
    layout="wide",
    page_icon="🩺",
    initial_sidebar_state="expanded",
)

# Estilização CSS
st.markdown(
    """
    <style>
    .main-header { font-size: 2.2rem; font-weight: 800; color: #1E3A8A; margin-bottom: 0.2rem; }
    .sub-header { font-size: 1.05rem; color: #4B5563; margin-bottom: 1.5rem; }
    .section-card { background-color: #F8FAFC; border: 1px solid #E2E8F0; padding: 1.5rem; border-radius: 12px; margin-bottom: 1.5rem; }
    .status-alert-grave { background-color: #FEE2E2; color: #991B1B; padding: 1rem; border-radius: 8px; font-weight: bold; }
    .status-alert-mod { background-color: #FEF3C7; color: #92400E; padding: 1rem; border-radius: 8px; font-weight: bold; }
    .status-alert-ok { background-color: #D1FAE5; color: #065F46; padding: 1rem; border-radius: 8px; font-weight: bold; }
    .stButton>button { width: 100%; font-weight: bold; height: 3rem; background-color: #2563EB; color: white; border-radius: 8px; }
    </style>
    """,
    unsafe_allow_html=True,
)


# --- DEFINIÇÃO EXPLICITA DAS PASTAS E FICHEIROS NA PASTA DO TÉCNICO ---
DIRETORIO_TECNICO = os.path.dirname(os.path.abspath(__file__))
FICHEIRO_PENDENTES = os.path.join(DIRETORIO_TECNICO, "pendentes.json")
PASTA_PDFS_PENDENTES = os.path.join(DIRETORIO_TECNICO, "relatorios_pdf")
PASTA_FOTOS_PENDENTES = os.path.join(DIRETORIO_TECNICO, "fotos_temp")
DB_LOCAL_NAME = "banco_central_nutricao.db"
EXCEL_TECNICOS = os.path.join(DIRETORIO_TECNICO, "tecnicos.xlsx")

# Garantir que as pastas locais existem dentro do diretório do técnico
os.makedirs(PASTA_PDFS_PENDENTES, exist_ok=True)
os.makedirs(PASTA_FOTOS_PENDENTES, exist_ok=True)


# URL de conexão com o Supabase (PostgreSQL)
DATABASE_URL = "postgresql://postgres.fconcnqghekmsgvzpgtn:uXbQ65NDnOkA3L6Q@db.fconcnqghekmsgvzpgtn.supabase.co:6543/postgres"


def get_db_engine():
  """Retorna a conexão SQLAlchemy com o Supabase ou fallback local."""
  try:
    engine = create_engine(DATABASE_URL, pool_size=5, max_overflow=10)
    with engine.connect() as conn:
      conn.execute(text("SELECT 1"))
    return engine
  except Exception:
    return create_engine(f"sqlite:///{DB_LOCAL_NAME}")


# --- INICIALIZAÇÃO DA TABELA DE TÉCNICOS E IMPORTAÇÃO DO EXCEL (OFFLINE) ---
def inicializar_base_tecnicos():
  engine = get_db_engine()
  try:
    with engine.begin() as conn:
      conn.execute(
          text("""
                CREATE TABLE IF NOT EXISTS tecnicos_offline (
                    username TEXT PRIMARY KEY,
                    senha_hash TEXT NOT NULL,
                    nome TEXT,
                    provincia TEXT,
                    distrito TEXT
                )
            """)
      )


      # Tabela de triagens robusta com campo gravidade
      conn.execute(
          text("""
                CREATE TABLE IF NOT EXISTS triagens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data_hora TEXT,
                    tecnico_username TEXT,
                    nome_paciente TEXT,
                    data_nascimento TEXT,
                    idade_formatada TEXT,
                    sexo TEXT,
                    raca TEXT,
                    nome_responsavel TEXT,
                    telefone TEXT,
                    provincia TEXT,
                    distrito TEXT,
                    bairro TEXT,
                    peso REAL,
                    altura REAL,
                    perimetro_braquial REAL,
                    perimetro_craniano REAL,
                    edema TEXT,
                    zscore REAL,
                    status TEXT,
                    gravidade TEXT,
                    conduta TEXT,
                    caminho_pdf TEXT
                )
            """)
      )


      # Lê o Excel de técnicos para suportar 2000+ offline
      if os.path.exists(EXCEL_TECNICOS):
        df = pd.read_excel(EXCEL_TECNICOS)
        for _, row in df.iterrows():
          user = str(row["username"]).strip()
          senha_plana = str(row["password"]).strip()
          nome_u = str(row.get("nome", user)).strip()
          prov_u = str(row.get("provincia", "Nampula")).strip()
          dist_u = str(row.get("distrito", "")).strip()

          senha_hash = hashlib.sha256(senha_plana.encode()).hexdigest()

          conn.execute(
              text("""
                        INSERT OR REPLACE INTO tecnicos_offline (username, senha_hash, nome, provincia, distrito)
                        VALUES (:u, :h, :n, :p, :d)
                    """),
              {
                  "u": user,
                  "h": senha_hash,
                  "n": nome_u,
                  "p": prov_u,
                  "d": dist_u,
              },
          )
      else:
        hash_exemplo = hashlib.sha256("123".encode()).hexdigest()
        conn.execute(
            text("""
                    INSERT OR IGNORE INTO tecnicos_offline (username, senha_hash, nome, provincia, distrito)
                    VALUES ('jmandala', :h, 'J. Mandala', 'Nampula', '')
                """),
            {"h": hash_exemplo},
        )
  except Exception as e:
    print(f"Erro ao inicializar base de dados: {e}")


inicializar_base_tecnicos()


# --- GESTÃO DE ESTADO DE AUTENTICAÇÃO ---
if "autenticado" not in st.session_state:
  st.session_state["autenticado"] = False
if "usuario_atual" not in st.session_state:
  st.session_state["usuario_atual"] = ""
if "nome_completo" not in st.session_state:
  st.session_state["nome_completo"] = ""
if "provincia_tec" not in st.session_state:
  st.session_state["provincia_tec"] = ""
if "distrito_tec" not in st.session_state:
  st.session_state["distrito_tec"] = ""


# --- ECRÃ DE LOGIN OBRIGATÓRIO (SE NÃO ESTIVER AUTENTICADO) ---
if not st.session_state["autenticado"]:
  st.markdown(
      "<div class='main-header' style='text-align: center;'>🩺 Acesso"
      " Restrito - Técnico</div>",
      unsafe_allow_html=True,
  )
  st.markdown(
      "<div class='sub-header' style='text-align: center;'>Insira as suas"
      " credenciais de técnico para aceder ao painel de campo</div>",
      unsafe_allow_html=True,
  )

  col_l1, col_l2, col_l3 = st.columns([1, 1.5, 1])
  with col_l2:
    with st.form("form_login_tecnico"):
      user_input = st.text_input("Username / Utilizador")
      pass_input = st.text_input("Password / Palavra-passe", type="password")
      submitted_login = st.form_submit_button("🔑 Entrar no Sistema")

      if submitted_login:
        if not user_input.strip() or not pass_input.strip():
          st.error("Preencha todos os campos de login.")
        else:
          engine = get_db_engine()
          login_sucesso = False
          try:
            with engine.connect() as conn:
              pass_hash_input = hashlib.sha256(
                  pass_input.encode()
              ).hexdigest()
              res_offline = conn.execute(
                  text(
                      "SELECT * FROM tecnicos_offline WHERE username = :u AND"
                      " senha_hash = :h"
                  ),
                  {"u": user_input, "h": pass_hash_input},
              ).fetchone()

              if res_offline:
                login_sucesso = True
                res_dict = dict(res_offline._mapping)
                st.session_state["autenticado"] = True
                st.session_state["usuario_atual"] = user_input
                st.session_state["nome_completo"] = res_dict.get(
                    "nome", user_input
                )
                st.session_state["provincia_tec"] = (
                    res_dict.get("provincia") or "Nampula"
                )
                st.session_state["distrito_tec"] = (
                    res_dict.get("distrito") or ""
                )
              else:
                query = text(
                    "SELECT * FROM usuarios WHERE username = :u AND password ="
                    " :p AND lower(tipo) LIKE '%tecnico%'"
                )
                resultado = conn.execute(
                    query, {"u": user_input, "p": pass_input}
                ).fetchone()

                if resultado:
                  login_sucesso = True
                  st.session_state["autenticado"] = True
                  st.session_state["usuario_atual"] = user_input
                  res_dict = dict(resultado._mapping)
                  st.session_state["nome_completo"] = res_dict.get(
                      "nome", user_input
                  )
                  prov = res_dict.get("provincia", "")
                  dist = res_dict.get("distrito", "")
                  st.session_state["provincia_tec"] = (
                      prov if prov else "Nampula"
                  )
                  st.session_state["distrito_tec"] = dist if dist else ""

              if login_sucesso:
                st.success(
                    "Login efetuado com sucesso! A carregar painel..."
                )
                st.rerun()
              else:
                st.error(
                    "Acesso negado: Utilizador, password incorretos ou conta"
                    " sem privilégios de TÉCNICO."
                )
          except Exception as e:
            st.error(f"Erro ao conectar com a base de dados: {e}")
    st.stop()


# ==============================================================================
# PAINEL COMPLETO DO TÉCNICO AUTENTICADO
# ==============================================================================

PROVINCIAS = [
    "Niassa",
    "Cabo Delgado",
    "Nampula",
    "Zambézia",
    "Tete",
    "Manica",
    "Sofala",
    "Inhambane",
    "Gaza",
    "Maputo Província",
    "Maputo Cidade",
]


# --- DICIONÁRIO DETALHADO DE ALIMENTOS E CONDUTAS POR PROVÍNCIA ---
ALIMENTOS_REGIONAIS_DETALHADOS = {
    "Nampula": {
        "alimentos_locais": (
            "Matapa de folha de mandioca com amendoim, peixe seco/fresco, papas"
            " de mexoeira ou milho enriquecidas com gergelim, feijão-nhemba,"
            " mandioca cozida e papaia fresca."
        ),
        "papas_enriquecidas": (
            "Papa de mexoeira com pó de amendoim torrado e gotas de limão"
            " (alta densidade calórica)."
        ),
        "conduta_terapeutica_local": (
            "Internamento em US / TAPE (ex: Marere) com F-75/F-100, ATPU e"
            " tratamento rigoroso de infecções associadas."
        ),
    },
    "Cabo Delgado": {
        "alimentos_locais": (
            "Matapa de folha de mandioca, peixe do mar fresco, papas de"
            " mexoeira, feijão-nhemba, mapira e coco ralado/leite de coco."
        ),
        "papas_enriquecidas": (
            "Papa de milho com leite de coco natural e pasta de amendoim."
        ),
        "conduta_terapeutica_local": (
            "Protocolo MISAU para Desnutrição Aguda Grave com edema: F-75 inicial"
            " + ReSoMal e cobertura antibiótica."
        ),
    },
    "Niassa": {
        "alimentos_locais": (
            "Papas de mexoeira ou mapira, peixe do lago Niassa (chambo),"
            " batata-doce, feijão e folhas verdes locais."
        ),
        "papas_enriquecidas": (
            "Papa de mapira enriquecida com farinha de feijão torrado."
        ),
        "conduta_terapeutica_local": (
            "Suplementação com ATPU e acompanhamento quinzenal na US de"
            " referência do distrito."
        ),
    },
    "Zambézia": {
        "alimentos_locais": (
            "Papas de mapira/mexoeira, folha de abóbora (m'fumo), peixe do rio"
            " (carpa/tilápia), feijão jugo e batata-doce de polpa alaranjada."
        ),
        "papas_enriquecidas": (
            "Papa de mapira com farinha de castanha ou pó de amendoim."
        ),
        "conduta_terapeutica_local": (
            "Estabilização com F-75 e transição rápida para F-100/ATPU conforme"
            " evolução clínica."
        ),
    },
    "Tete": {
        "alimentos_locais": (
            "Papas de mapira e milho, feijão-boer, abóbora, peixe seco do rio"
            " Zambeze e folhas de abóbora."
        ),
        "papas_enriquecidas": "Papa de milho enriquecida com pó de feijão-boer.",
        "conduta_terapeutica_local": (
            "Internamento hospitalar se houver complicações graves (anemia,"
            " infeção sistémica)."
        ),
    },
    "Manica": {
        "alimentos_locais": (
            "Batata-doce alaranjada, milho, feijão manteiga, hortaliças da"
            " região e fruta fresca (manga, banana)."
        ),
        "papas_enriquecidas": (
            "Papa mista de milho com puré de batata-doce e amendoim."
        ),
        "conduta_terapeutica_local": (
            "Acompanhamento em consultas de nutrição com distribuição de ATPU"
            " quinzenal."
        ),
    },
    "Sofala": {
        "alimentos_locais": (
            "Arroz local, peixe fresco do mar e do rio, matapa de folhas de"
            " mandioca ou batata, feijão e coco."
        ),
        "papas_enriquecidas": (
            "Papa de arroz ou milho com amendoim triturado."
        ),
        "conduta_terapeutica_local": (
            "Protocolo padrão MISAU para reabilitação nutricional intensiva."
        ),
    },
    "Inhambane": {
        "alimentos_locais": (
            "Matapa de cacana ou couve com amendoim, marisco e peixe fresco,"
            " mandioca, feijão-nhemba e fruta (cajus, maçala)."
        ),
        "papas_enriquecidas": (
            "Papa de milho com massa de amendoim e polpa de caju/fruta."
        ),
        "conduta_terapeutica_local": (
            "Avaliação e suplementação ativa com micronutrientes e ATPU."
        ),
    },
    "Gaza": {
        "alimentos_locais": (
            "Mandioca, feijão-nhemba, abóbora, milho, couve local e peixe seco."
        ),
        "papas_enriquecidas": (
            "Papa de milho com puré de abóbora e amendoim torrado."
        ),
        "conduta_terapeutica_local": (
            "Consulta de rotina e controlo de peso quinzenal nas US locais."
        ),
    },
    "Maputo Província": {
        "alimentos_locais": (
            "Matapa de couve/cacana com amendoim, feijão, peixe do mar, frango"
            " e batata-doce."
        ),
        "papas_enriquecidas": (
            "Papa enriquecida com farinha de milho, amendoim e leite."
        ),
        "conduta_terapeutica_local": (
            "Internamento ou ambulatório dependendo do grau de desnutrição e"
            " comorbilidades."
        ),
    },
    "Maputo Cidade": {
        "alimentos_locais": (
            "Dieta diversificada baseada em produtos de mercado urbano,"
            " hortaliças frescas, peixe, carne magra e leguminosas."
        ),
        "papas_enriquecidas": (
            "Papas fortificadas comerciais ou caseiras com amendoim e fruta."
        ),
        "conduta_terapeutica_local": (
            "Acompanhamento em centro de saúde urbano com suporte clínico"
            " completo."
        ),
    },
}


def limpar_emojis_para_pdf(texto: str) -> str:
  if not texto:
    return ""
  return re.sub(r"[^\x00-\xFF]", "", texto)


def analisar_imagem_paciente_ia(caminho_foto):
  """Utiliza OpenCV e Pillow para pré-processar e extrair métricas visuais da foto do paciente/lesão."""
  if not caminho_foto or not os.path.exists(caminho_foto):
    return "Nenhuma imagem capturada para análise automatizada de visão."
  try:
    img_cv = cv2.imread(caminho_foto)
    if img_cv is None:
      return "Erro ao carregar a imagem para processamento."
    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    brilho_medio = np.mean(gray)
    contraste = np.std(gray)

    relatorio_ia = (
        f"🤖 **Análise de Visão Computacional (IA local):**\n"
        f"- Brilho Médio da Pele/Lesão: {brilho_medio:.1f}\n"
        f"- Índice de Contraste Textural: {contraste:.1f}\n"
    )
    if brilho_medio < 80:
      relatorio_ia += (
          "- *Alerta IA:* Detetada possível área de hiperpigmentação ou lesão"
          " cutânea grave associada a Kwashiorkor."
      )
    else:
      relatorio_ia += (
          "- *Status IA:* Sem alterações severas detetadas por matriz ótica"
          " imediata."
      )
    return relatorio_ia
  except Exception as e:
    return f"Erro na execução da Visão Computacional: {e}"


def obter_recomendacao_detalhada(provincia, distrito, status_diagnostico, idade_anos):
  dados_prov = ALIMENTOS_REGIONAIS_DETALHADOS.get(
      provincia, ALIMENTOS_REGIONAIS_DETALHADOS["Nampula"]
  )
  alimentos = dados_prov["alimentos_locais"]
  papas = dados_prov["papas_enriquecidas"]
  conduta_local = dados_prov["conduta_terapeutica_local"]
  local_str = f"Distrito de {distrito} ({provincia})"

  if "Grave" in status_diagnostico or "Kwashiorkor" in status_diagnostico:
    return (
        f"🚨 **URGENTE ({local_str}):**\n"
        f"- **Conduta Terapêutica:** {conduta_local}\n"
        f"- **Apoio Alimentar Local / Transição:** {papas}\n"
        f"- **Dieta de Reabilitação:** {alimentos}"
    )

  elif "Moderad" in status_diagnostico or "Baixo Peso" in status_diagnostico:
    return (
        f"🟡 **ATENÇÃO NUTRICIONAL ({local_str}):**\n"
        f"- **Conduta:** Acompanhamento quinzenal na Unidade Sanitária.\n"
        f"- **Papa Recomendada:** {papas}\n"
        f"- **Alimentos Base da Região:** {alimentos}"
    )

  elif "Sobrepeso" in status_diagnostico or "Obesidade" in status_diagnostico:
    return (
        f"🟠 **REEDUCAÇÃO ALIMENTAR ({local_str}):**\n"
        f"- Reduzir açúcares refinados, óleos e fritos.\n"
        f"- Priorizar vegetais locais, mandioca cozida, peixe fresco e fruta da época."
    )

  return (
      f"🟢 **MANUTENÇÃO DE EUTROFIA ({local_str}):**\n"
      f"- Manter alimentação variada e equilibrada baseada em: {alimentos}"
  )


def calcular_idade_detalhada(data_nasc):
  hoje = datetime.now().date()
  anos = hoje.year - data_nasc.year
  meses = hoje.month - data_nasc.month
  dias = hoje.day - data_nasc.day

  if dias < 0:
    meses -= 1
  if meses < 0:
    anos -= 1
    meses += 12

  total_meses = (anos * 12) + meses
  return max(0, anos), max(0, total_meses)


def diagnosticar_nutricao_completo(
    idade_anos, total_meses, peso, altura, pb, edema
):
  altura_m = altura / 100.0 if altura > 3.0 else altura
  imc = round(peso / (altura_m**2), 2) if altura_m > 0 else 0.0

  if total_meses <= 60:
    if edema in ["+", "++", "+++"]:
      return (
          "Desnutrição Aguda Grave (Kwashiorkor / Edema Bilateral)",
          "Nível 3 - Gravíssimo",
          imc,
      )
    if 0.0 < pb < 11.5:
      return (
          "Desnutrição Aguda Grave (DAG) por PB",
          "Nível 3 - Grave",
          imc,
      )
    elif 11.5 <= pb < 12.5:
      return (
          "Desnutrição Aguda Moderada (DAM) por PB",
          "Nível 2 - Moderado",
          imc,
      )
    elif 12.5 <= pb < 13.5:
      return "Risco de Desnutrição por PB", "Nível 2 - Alerta", imc

    if imc < 13.0:
      return "Desnutrição Severa (Abaixo P3)", "Nível 3 - Grave", imc
    elif 13.0 <= imc < 14.5:
      return "Desnutrição Moderada", "Nível 2 - Moderado", imc
    elif 14.5 <= imc < 18.0:
      return "Estado Nutricional Normal (Eutrofia)", "Nível 1 - Normal", imc
    elif 18.0 <= imc < 19.5:
      return "Risco de Sobrepeso", "Nível 2 - Alerta", imc
    else:
      return "Obeso / Músculo ou Gordura Elevada", "Nível 3 - Elevado", imc

  elif 6 <= idade_anos <= 19:
    if imc < 13.5:
      return "Magreza Acentuada / Desnutrição Severa", "Nível 3 - Grave", imc
    elif 13.5 <= imc < 15.5:
      return "Magreza Moderada", "Nível 2 - Moderado", imc
    elif 15.5 <= imc < 22.0:
      return "Eutrofia (Peso Adequado)", "Nível 1 - Normal", imc
    elif 22.0 <= imc < 26.0:
      return "Sobrepeso", "Nível 2 - Moderado", imc
    else:
      return "Obesidade Juvenil", "Nível 3 - Elevado", imc

  elif 20 <= idade_anos <= 59:
    if imc < 16.0:
      return "Desnutrição / Magreza Severa (Grau III)", "Nível 3 - Grave", imc
    elif 16.0 <= imc < 17.0:
      return "Magreza Moderada (Grau II)", "Nível 2 - Moderado", imc
    elif 17.0 <= imc < 18.5:
      return "Magreza Leve (Grau I)", "Nível 2 - Alerta", imc
    elif 18.5 <= imc < 25.0:
      return "Eutrofia (Peso Normal)", "Nível 1 - Normal", imc
    elif 25.0 <= imc < 30.0:
      return "Sobrepeso (Pré-Obesidade)", "Nível 2 - Alerta", imc
    elif 30.0 <= imc < 35.0:
      return "Obesidade Classe I", "Nível 3 - Moderado", imc
    elif 35.0 <= imc < 40.0:
      return "Obesidade Classe II (Severa)", "Nível 3 - Grave", imc
    else:
      return "Obesidade Classe III (Mórbida)", "Nível 3 - Gravíssimo", imc

  else:
    if imc < 22.0:
      return "Baixo Peso / Desnutrição no Idoso", "Nível 3 - Grave", imc
    elif 22.0 <= imc < 27.0:
      return "Eutrofia (Peso Adequado para Idoso)", "Nível 1 - Normal", imc
    elif 27.0 <= imc < 30.0:
      return "Sobrepeso em Idoso", "Nível 2 - Moderado", imc
    else:
      return "Obesidade em Idoso", "Nível 3 - Elevado", imc


def carregar_pendentes_locais():
  if os.path.exists(FICHEIRO_PENDENTES):
    try:
      with open(FICHEIRO_PENDENTES, "r", encoding="utf-8") as f:
        return json.load(f)
    except Exception:
      return []
  return []


def guardar_pendente_local(objeto_offline):
  pendentes = carregar_pendentes_locais()
  pendentes.append(objeto_offline)
  with open(FICHEIRO_PENDENTES, "w", encoding="utf-8") as f:
    json.dump(pendentes, f, ensure_ascii=False, indent=4)


def limpar_pendentes_locais():
  if os.path.exists(FICHEIRO_PENDENTES):
    try:
      os.remove(FICHEIRO_PENDENTES)
    except Exception:
      pass


def sincronizar_registos_pendentes():
  pendentes = carregar_pendentes_locais()
  if not pendentes:
    return True, "Não existem registos pendentes por sincronizar."

  engine = get_db_engine()
  pendentes_mantidos = []

  for registro in pendentes:
    params = registro.get("params_db")
    try:
      with engine.begin() as conn:
        conn.execute(
            text("""
                    INSERT INTO triagens (
                        data_hora, tecnico_username, nome_paciente, data_nascimento, idade_formatada,
                        sexo, raca, nome_responsavel, telefone, provincia, distrito, bairro,
                        peso, altura, perimetro_braquial, perimetro_craniano, edema, zscore, status, gravidade, conduta, caminho_pdf
                    ) VALUES (
                        :dh, :tu, :np, :dn, :if, :sx, :rc, :nr, :tf, :pr, :ds, :br, :ps, :al, :pb, :pc, :ed, :zs, :st, :gr, :cd, :pdf
                    )
                """),
            params,
        )
    except Exception:
      pendentes_mantidos.append(registro)

  if not pendentes_mantidos:
    limpar_pendentes_locais()
    return True, "🟢 Registos sincronizados com sucesso para o Supabase!"
  else:
    with open(FICHEIRO_PENDENTES, "w", encoding="utf-8") as f:
      json.dump(pendentes_mantidos, f, ensure_ascii=False, indent=4)
    return (
        False,
        "⚠️ Alguns registos continuam salvos localmente para novo envio.",
    )


def gerar_pdf_laudo_tecnico(dados_dict, caminho_saida_pdf, caminho_foto=None):
  pdf = FPDF()
  pdf.add_page()
  pdf.set_auto_page_break(auto=True, margin=15)

  pdf.set_font("Arial", "B", 14)
  pdf.cell(
      190,
      8,
      txt="REPÚBLICA DE MOÇAMBIQUE - SERVIÇO NACIONAL DE SAÚDE",
      ln=True,
      align="C",
  )
  pdf.set_font("Arial", "B", 12)
  pdf.cell(
      190,
      6,
      txt="MÚLTI-CARTÃO DE TRATAMENTO TERAPÊUTICO PARA DESNUTRIÇÃO",
      ln=True,
      align="C",
  )
  pdf.set_font("Arial", "I", 9)
  pdf.cell(
      190,
      5,
      txt=(
          f"Emissão: {dados_dict['data_hora']} | Técnico:"
          f" {limpar_emojis_para_pdf(dados_dict['tecnico'])}"
      ),
      ln=True,
      align="C",
  )
  pdf.ln(4)

  pdf.set_line_width(0.5)
  pdf.line(10, pdf.get_y(), 200, pdf.get_y())
  pdf.ln(4)

  pdf.set_font("Arial", "B", 12)
  pdf.cell(190, 6, txt="1. IDENTIFICAÇÃO E LOCALIZAÇÃO DO PACIENTE", ln=True)
  pdf.set_font("Arial", "", 9)
  pdf.cell(
      95, 5, txt=f"N.º de Ordem Mensal: {dados_dict['num_ordem']}", ln=False
  )
  pdf.cell(95, 5, txt=f"NID: {dados_dict['nid']}", ln=True)
  pdf.cell(
      190,
      5,
      txt=f"Nome do Doente: {limpar_emojis_para_pdf(dados_dict['paciente'])}",
      ln=True,
  )
  pdf.cell(
      95,
      5,
      txt=(
          f"Data Nasc.: {dados_dict['data_nasc']} ({dados_dict['idade_anos']}"
          " Anos)"
      ),
      ln=False,
  )
  pdf.cell(95, 5, txt=f"Sexo: {dados_dict['sexo']}", ln=True)
  pdf.cell(
      95,
      5,
      txt=(
          "Acompanhante:"
          f" {limpar_emojis_para_pdf(dados_dict['responsavel'])}"
      ),
      ln=False,
  )
  pdf.cell(95, 5, txt=f"Contacto: {dados_dict['telefone']}", ln=True)
  pdf.cell(
      95,
      5,
      txt=(
          f"Província: {dados_dict['provincia']} | Dist:"
          f" {dados_dict['distrito']}"
      ),
      ln=False,
  )
  pdf.cell(95, 5, txt=f"Unidade Sanitária (US): {dados_dict['us']}", ln=True)
  pdf.cell(
      95,
      5,
      txt=(
          f"Nº Quarto: {dados_dict['num_quarto']} | Nº Cama:"
          f" {dados_dict['num_cama']}"
      ),
      ln=False,
  )
  pdf.cell(95, 5, txt=f"Distância à US: {dados_dict['distancia_us']}", ln=True)
  pdf.cell(
      95,
      5,
      txt=f"Data Internamento: {dados_dict['data_internamento']}",
      ln=False,
  )
  pdf.cell(95, 5, txt=f"Tipo Admissão: {dados_dict['tipo_admissao']}", ln=True)
  pdf.ln(3)

  pdf.set_font("Arial", "B", 12)
  pdf.cell(190, 6, txt="2. MAPA ANTROPOMÉTRICO E DIAGNÓSTICO", ln=True)
  pdf.set_font("Arial", "", 9)
  pdf.cell(63, 5, txt=f"Peso: {dados_dict['peso']} kg", ln=False)
  pdf.cell(63, 5, txt=f"Estatura: {dados_dict['altura']} cm", ln=False)
  pdf.cell(64, 5, txt=f"Peso Alvo: {dados_dict['peso_alvo']} kg", ln=True)
  pdf.cell(63, 5, txt=f"P/E (D/P): {dados_dict['pe_dp']}", ln=False)
  pdf.cell(63, 5, txt=f"PB: {dados_dict['pb']} cm", ln=False)
  pdf.cell(64, 5, txt=f"Edema: {dados_dict['edema']}", ln=True)
  pdf.cell(95, 5, txt=f"IMC/Idade: {dados_dict['imc']}", ln=False)
  pdf.cell(
      95,
      5,
      txt=f"Diagnóstico: {limpar_emojis_para_pdf(dados_dict['status'])}",
      ln=True,
  )
  pdf.ln(3)

  pdf.set_font("Arial", "B", 12)
  pdf.cell(190, 6, txt="3. TESTES, CONTROLO CLÍNICO E TRATAMENTO", ln=True)
  pdf.set_font("Arial", "", 9)
  pdf.cell(
      95,
      5,
      txt=(
          f"HIV: {dados_dict['teste_hiv']} | TB: {dados_dict['teste_tb']}"
      ),
      ln=False,
  )
  pdf.cell(
      95,
      5,
      txt=(
          f"Malária: {dados_dict['teste_malaria']} | Glicemia:"
          f" {dados_dict['glicemia']}"
      ),
      ln=True,
  )
  pdf.cell(
      190,
      5,
      txt=(
          "Complicações:"
          f" {limpar_emojis_para_pdf(dados_dict['complicacoes'])}"
      ),
      ln=True,
  )
  pdf.cell(95, 5, txt=f"Febre/Temp: {dados_dict['temp_ax_rec']}", ln=False)
  pdf.cell(
      95,
      5,
      txt=(
          f"Desidratação: {dados_dict['desidratacao']} | Vómito:"
          f" {dados_dict['vomito']}"
      ),
      ln=True,
  )
  pdf.cell(
      190,
      5,
      txt=(
          "Medicamentos de Rotina:"
          f" {limpar_emojis_para_pdf(dados_dict['meds_rotina'])}"
      ),
      ln=True,
  )
  pdf.cell(
      190,
      5,
      txt=(
          "Dieta Terapêutica:"
          f" {limpar_emojis_para_pdf(dados_dict['dieta_terapeutica'])}"
      ),
      ln=True,
  )
  pdf.ln(3)

  pdf.set_font("Arial", "B", 12)
  pdf.cell(190, 6, txt="4. RECOMENDAÇÃO NUTRICIONAL REGIONAL", ln=True)
  pdf.set_font("Arial", "", 9)
  recomendacao_limpa = limpar_emojis_para_pdf(dados_dict["recomendacao"])
  pdf.multi_cell(190, 5, txt=recomendacao_limpa)
  pdf.ln(4)

  # --- SECÇÃO DE REGISTO FOTOGRÁFICO ---
  pdf.set_font("Arial", "B", 12)
  pdf.cell(190, 6, txt="REGISTO FOTOGRÁFICO E ANÁLISE COMPUTACIONAL", ln=True)
  pdf.ln(2)

  if caminho_foto and os.path.exists(caminho_foto):
    try:
      y_inicio = pdf.get_y()

      # Coluna Esquerda: Inserir a Foto Real
      pdf.image(caminho_foto, x=10, y=y_inicio, w=60)

      # Coluna Direita: Inserir a Análise
      pdf.set_xy(75, y_inicio)
      pdf.set_font("Arial", "B", 9)
      pdf.cell(125, 5, txt="Análise de Visão Computacional (local):", ln=True)

      img_cv = cv2.imread(caminho_foto)
      if img_cv is not None:
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        brilho_medio = np.mean(gray)
        contraste = np.std(gray)
        status_ia = (
            "Alerta: Possível hiperpigmentação/lesão."
            if brilho_medio < 80
            else "Status: Sem alterações severas detetadas."
        )

        texto_ia_pdf = (
            f"- Brilho Médio da Pele/Lesão: {brilho_medio:.1f}\n"
            f"- Índice de Contraste Textural: {contraste:.1f}\n"
            f"- {status_ia}"
        )
      else:
        texto_ia_pdf = "Dados de visão computacional indisponíveis."

      pdf.set_xy(75, y_inicio + 6)
      pdf.set_font("Arial", "", 9)
      pdf.multi_cell(125, 5, txt=limpar_emojis_para_pdf(texto_ia_pdf))

      pdf.set_y(max(y_inicio + 55, pdf.get_y() + 10))

    except Exception as e:
      pdf.set_font("Arial", "I", 9)
      pdf.cell(
          190,
          5,
          txt=f"Não foi possível renderizar a imagem e a análise lado a lado: {e}",
          ln=True,
      )
  else:
    pdf.set_font("Arial", "I", 9)
    pdf.cell(190, 5, txt="Nenhuma fotografia capturada para este registo.", ln=True)

  pdf.output(caminho_saida_pdf)


# --- SIDEBAR COM DADOS DO TÉCNICO AUTENTICADO ---
st.sidebar.title("📌 Menu do Técnico")
st.sidebar.info(
    f"👤 **{st.session_state['nome_completo']}**\n\n📍 **Jurisdição:**"
    f" {st.session_state['provincia_tec']} /"
    f" {st.session_state['distrito_tec'] if st.session_state['distrito_tec'] else 'Geral'}"
)

if st.sidebar.button("🚪 Terminar Sessão"):
  st.session_state["autenticado"] = False
  st.session_state["usuario_atual"] = ""
  st.session_state["nome_completo"] = ""
  st.session_state["provincia_tec"] = ""
  st.session_state["distrito_tec"] = ""
  st.rerun()

st.sidebar.markdown("---")
st.sidebar.info("Modo **Sincronização Discreta Supabase** ativo.")

pendentes = carregar_pendentes_locais()
if len(pendentes) > 0:
  st.sidebar.warning(f"📦 Pendentes Offline: **{len(pendentes)}**")
  if st.sidebar.button("📡 Sincronizar com Nuvem"):
    with st.spinner("Enviando dados..."):
      sucesso, msg = sincronizar_registos_pendentes()
      if sucesso:
        st.sidebar.success(msg)
        st.rerun()
      else:
        st.sidebar.error(msg)
else:
  st.sidebar.success("🟢 Dispositivo sincronizado.")

# ==============================================================================
# DASHBOARD DIÁRIO DE ATENDIMENTOS NO PAINEL DO TÉCNICO (SEPARADO POR GRAVIDADE)
# ==============================================================================
st.sidebar.markdown("---")
st.sidebar.subheader("📊 RELAORIO DIARIO")

data_hoje_str = datetime.now().strftime("%d/%m/%Y")
engine_dash = get_db_engine()
try:
  with engine_dash.connect() as conn_d:
    query_dash = text(
        "SELECT gravidade FROM triagens WHERE tecnico_username = :tu AND"
        " data_hora LIKE :dh"
    )
    registos_hoje = conn_d.execute(
        query_dash,
        {"tu": st.session_state["nome_completo"], "dh": f"{data_hoje_str}%"},
    ).fetchall()

    total_hoje = len(registos_hoje)
    graves = sum(
        1
        for r in registos_hoje
        if "Grave" in str(r[0]) or "Gravíssimo" in str(r[0])
    )
    moderados = sum(
        1
        for r in registos_hoje
        if "Moderado" in str(r[0]) or "Alerta" in str(r[0])
    )
    normais = total_hoje - (graves + moderados)

    st.sidebar.metric("Total Atendidos Hoje", total_hoje)
    st.sidebar.markdown(f"🔴 **Casos Graves:** {graves}")
    st.sidebar.markdown(f"🟡 **Casos Moderados:** {moderados}")
    st.sidebar.markdown(f"🟢 **Casos Normais:** {normais}")
except Exception:
  st.sidebar.info("Dashboard a aguardar o primeiro registo de hoje.")

# --- INTERFACE DO TÉCNICO DE CAMPO ---
st.markdown(
    "<div class='main-header'>🩺 Triagem Nutricional</div>",
    unsafe_allow_html=True,
)
st.markdown(
    "<div class='sub-header'>Técnico Responsável:"
    f" <b>{st.session_state['nome_completo']}</b> | Zona:"
    f" <b>{st.session_state['provincia_tec']}</b></div>",
    unsafe_allow_html=True,
)

# --- FORMULÁRIO COMPLETO BASEADO NAS FICHAS DO MISAU ---
with st.form("form_multi_cartao_misau"):

  # --- SEÇÃO 1: IDENTIFICAÇÃO E LOCALIZAÇÃO ---
  st.markdown("<div class='section-card'>", unsafe_allow_html=True)
  st.subheader("1. Identificação e Localização (Ficha do Doente)")

  col1, col2, col3 = st.columns(3)
  with col1:
    num_ordem = st.text_input("Nº de Ordem Mensal")
    nid = st.text_input("NID (Nº de Identificação do Doente)")
    nome_paciente = st.text_input("Nome do Doente *")

    # Correção do limite de idade: Permite até 120 anos atrás (adultos e idosos)
    data_minima_nasc = date(date.today().year - 120, 1, 1)
    data_nascimento = st.date_input(
        "Data de Nascimento *",
        value=date(1999, 9, 1),
        min_value=data_minima_nasc,
        max_value=date.today(),
    )

    sexo = st.radio("Sexo *", ["Masculino", "Feminino"], horizontal=True)

  with col2:
    nome_responsavel = st.text_input("Nome do Acompanhante / Responsável *")
    telefone = st.text_input("Contacto Telefónico *")
    prov_index = (
        PROVINCIAS.index(st.session_state["provincia_tec"])
        if st.session_state["provincia_tec"] in PROVINCIAS
        else 0
    )
    provincia = st.selectbox("Província *", PROVINCIAS, index=prov_index)
    distrito = st.text_input("Distrito *", value=st.session_state["distrito_tec"])
    unidade_sanitaria = st.text_input("Unidade Sanitária (US) *")

  with col3:
    num_quarto = st.text_input("N.º do Quarto")
    num_cama = st.text_input("N.º da Cama")
    bairro = st.text_input("Endereço / Bairro *")
    distancia_us = st.text_input("Distância da casa à US (ex: 5 km)")
    data_internamento = st.date_input(
        "Data de Internamento", value=date.today()
    )

  st.markdown("---")
  st.markdown("**Informações de Admissão e Alimentação do Doente:**")
  col_adm1, col_adm2, col_adm3 = st.columns(3)
  with col_adm1:
    tipo_admissao = st.selectbox(
        "Tipo de Caso (Admissão)",
        [
            "Caso Novo",
            "Referido do TDA",
            "Transferido de outro sector",
            "Abandono que retorna",
        ],
    )
  with col_adm2:
    aleitamento_materno = st.radio(
        "Aleitamento Materno?", ["Sim", "Não"], horizontal=True
    )
  with col_adm3:
    alimentacao_complementar = st.radio(
        "Alimentação Complementar?", ["Sim", "Não"], horizontal=True
    )

  st.markdown("</div>", unsafe_allow_html=True)

  # --- SEÇÃO 2: AVALIAÇÃO ANTROPOMÉTRICA & DIAGNÓSTICO ---
  st.markdown("<div class='section-card'>", unsafe_allow_html=True)
  st.subheader("2. Mapa Antropométrico & Diagnóstico")

  col_ant1, col_ant2, col_ant3 = st.columns(3)
  with col_ant1:
    peso = st.number_input(
        "Peso (kg) *", min_value=0.5, max_value=250.0, value=12.0, step=0.1
    )
    estatura = st.number_input(
        "Estatura / Altura (cm) *",
        min_value=30.0,
        max_value=230.0,
        value=80.0,
        step=0.5,
    )
    peso_alvo = st.number_input(
        "Peso Alvo (kg)", min_value=0.0, max_value=250.0, value=14.0, step=0.1
    )

  with col_ant2:
    perimetro_braquial = st.number_input(
        "PB - Perímetro Braquial (cm)",
        min_value=0.0,
        max_value=60.0,
        value=14.0,
        step=0.1,
    )
    pe_dp = st.selectbox(
        "P/E - Peso/Estatura (D/P)",
        [
            "Normal",
            "Desvio Padrão -1",
            "Desvio Padrão -2",
            "Desvio Padrão -3",
            "< -3 SD",
        ],
    )
    edema = st.selectbox(
        "Edema Bilateral *",
        ["0 (Ausente)", "+ (Leve)", "++ (Moderado)", "+++ (Grave)"],
    )

  with col_ant3:
    st.markdown("**Critérios Diagnósticos MISAU:**")
    st.info(
        "O sistema calcula automaticamente o IMC e a gravidade com base no"
        " peso, altura, PB e Edema para todas as faixas etárias."
    )

  st.markdown("</div>", unsafe_allow_html=True)

  # --- SEÇÃO 3: TESTES LABORATORIAIS E CLÍNICOS ---
  st.markdown("<div class='section-card'>", unsafe_allow_html=True)
  st.subheader("3. Resultados dos Testes Clínicos / Laboratoriais")

  col_t1, col_t2, col_t3 = st.columns(3)
  with col_t1:
    teste_hiv = st.selectbox(
        "Teste HIV", ["Não Realizado", "Negativo", "Positivo", "Indeterminado"]
    )
    teste_tb = st.selectbox(
        "Teste TB (Tuberculose)",
        ["Não Realizado", "Negativo", "Positivo", "Suspeito"],
    )

  with col_t2:
    glicemia = st.text_input("Glicemia (mg/dL)", value="Normal")
    teste_malaria = st.selectbox(
        "Teste de Malária",
        [
            "Não Realizado",
            "Negativo",
            "Positivo (TDR)",
            "Positivo (Lâmina)",
        ],
    )

  with col_t3:
    hemograma = st.text_input("Hemograma / Hb (g/dL)", value="11.0")

  st.markdown("</div>", unsafe_allow_html=True)

  # --- SEÇÃO 4: MAPA DE CONTROLO CLÍNICO & COMPLICAÇÕES ---
  st.markdown("<div class='section-card'>", unsafe_allow_html=True)
  st.subheader("4. Mapa de Controlo Clínico & Complicações")

  with st.expander("🔍 Expandir / Selecionar Sinais e Sintomas de Controlo"):
    c_ctrl1, c_ctrl2, c_ctrl3 = st.columns(3)

    with c_ctrl1:
      complicacoes = st.multiselect(
          "Complicações Importantes Identificadas",
          [
              "Nenhuma",
              "Hipoglicemia",
              "Hipotermia",
              "Infeção Grave",
              "Anemia Severa",
              "Lesões de Pele",
              "Anorexia",
          ],
      )
      desidratacao = st.selectbox(
          "Desidratação",
          ["0 (Ausente)", "+ (Ligeira)", "++ (Moderada)", "+++ (Grave)"],
      )
      vomito = st.radio(
          "Vómito",
          ["Ausente", "Ligeiro", "Frequente", "Persistente"],
          horizontal=True,
      )

    with c_ctrl2:
      dejeccoes = st.selectbox(
          "Dejecções (Diarreia)",
          ["Normais", "+ (1-3/dia)", "++ (4-6/dia)", "+++ (>6/dia ou Líquida)"],
      )
      tosse = st.radio("Tosse Presente?", ["Não", "Sim"], horizontal=True)
      choque_septico = st.radio(
          "Choque Séptico?", ["Não", "Sim"], horizontal=True
      )

    with c_ctrl3:
      freq_respiratoria = st.text_input(
          "Frequência Respiratoria (rpm)", value="30"
      )
      temp_ax_rec = st.text_input(
          "Temperatura Axilar/Rectal (°C)", value="36.5"
      )
      conjuntivas_palidas = st.radio(
          "Conjuntivas Pálidas?", ["Não", "Sim"], horizontal=True
      )
      dermatite = st.selectbox(
          "Dermatite",
          ["0 (Ausente)", "+ (Ligeira)", "++ (Moderada)", "+++ (Extensa)"],
      )
      tamanho_figado = st.text_input(
          "Tamanho do Fígado (cm)", value="Normal"
      )
      freq_cardiaca = st.text_input("Frequência Cardíaca (bpm)", value="90")

  st.markdown("</div>", unsafe_allow_html=True)

  # --- SEÇÃO 5: TRATAMENTO & DIETA TERAPÊUTICA ---
  st.markdown("<div class='section-card'>", unsafe_allow_html=True)
  st.subheader("5. Medicamentos e Dieta Terapêutica")

  with st.expander("💊 Selecionar Medicamentos de Rotina, Especiais e Dieta"):
    c_med1, c_med2 = st.columns(2)

    with c_med1:
      st.markdown("**Medicamentos de Rotina:**")
      med_acido_folico = st.checkbox("Ácido Fólico")
      med_antibiotico1 = st.text_input(
          "Antibiótico 1 (ex: Amoxicilina)", value="Amoxicilina"
      )
      med_antibiotico2 = st.text_input("Antibiótico 2 / Outros", value="")
      med_vitamina_a = st.text_input("Vitamina A (UI)", value="200.000 UI")

      st.markdown("**Medicamentos e Equipamentos Especiais:**")
      med_suplemento_ferro = st.checkbox("Suplemento de Ferro")
      med_antimalarico = st.checkbox("Anti-malárico")
      med_antihelmintico = st.checkbox(
          "Anti-helmíntico (Mebendazol/Albendazol)"
      )
      med_resomal = st.checkbox("ReSoMal (ml)")
      med_fluido_iv = st.checkbox("Fluído IV / Sangue")
      med_sonda_ng = st.checkbox("Uso de Sonda Nasogástrica (NG)")

    with c_med2:
      st.markdown("**Dieta Terapêutica:**")
      fase_dieta = st.selectbox(
          "Fase da Dieta Terapêutica",
          [
              "Fase 1 (F-75)",
              "Transição (F-75/F-100)",
              "Fase 2 (F-100 / ATPU)",
              "Reabilitação",
          ],
      )
      atpu = st.radio(
          "ATPU / RUFT (Alimento Terapêutico Pronto a Usar)",
          ["Não", "Sim"],
          horizontal=True,
      )
      qtd_tomada = st.select_slider(
          "Quantidade Tomada da Dieta", options=["1/4", "1/2", "3/4", "100%"]
      )
      refeicao_familiar = st.checkbox("Refeição Familiar Iniciada")
      papa_farinha = st.checkbox("Papa de Farinha Enriquecida")

  st.markdown("</div>", unsafe_allow_html=True)

  # --- SEÇÃO 6: IMUNIZAÇÃO E EDUCAÇÃO NA ALTA ---
  st.markdown("<div class='section-card'>", unsafe_allow_html=True)
  st.subheader("6. Datas de Imunização (Vacinação) & Educação na Alta")

  with st.expander("📋 Registrar Vacinas e Tópicos de Educação Nutricional"):
    c_vac1, c_vac2 = st.columns(2)

    with c_vac1:
      st.markdown("**Estado de Imunização (Vacinas em dia?):**")
      vacina_bcg = st.checkbox("BCG", value=True)
      vacina_polio = st.checkbox("Pólio", value=True)
      vacina_dpt = st.checkbox("DPT / Pentavalente / Hep B", value=True)
      vacina_sarampo = st.checkbox("Sarampo", value=True)
      vacina_ira = st.checkbox("IRA", value=True)

    with c_vac2:
      st.markdown("**Educação Dada na Alta / Consulta:**")
      edu_causas = st.checkbox("Causas de Malnutrição")
      edu_diarreia = st.checkbox("Diarreia, ITR, Febre")
      edu_pele = st.checkbox("Infeções da pele, olhos e ouvidos")
      edu_brincar = st.checkbox("Brincar e estimulação")
      edu_alimentacao = st.checkbox("Alimentação da criança", value=True)
      edu_higiene = st.checkbox("Cuidados de Higiene", value=True)
      edu_planeamento = st.checkbox("Planeamento Familiar")
      edu_vitamina_a = st.checkbox("Vitamina A dada", value=True)

  st.markdown("</div>", unsafe_allow_html=True)

  # --- SEÇÃO 7: TÉCNICO RESPONSÁVEL ---
  st.markdown("<div class='section-card'>", unsafe_allow_html=True)
  st.subheader("7. Identificação do Técnico Responsável")
  nome_tecnico = st.text_input(
      "Nome / Código do Técnico Responsável *",
      value=st.session_state["nome_completo"],
      disabled=True,
  )
  st.markdown("</div>", unsafe_allow_html=True)

  # --- SEÇÃO 8: TIRAR FOTO DO PACIENTE E CONVERTER FOTO ---
  st.markdown("<div class='section-card'>", unsafe_allow_html=True)
  st.subheader("📷 Tirar Foto do Paciente")
  foto_buffer = st.camera_input("Capturar Imagem do Paciente / Lesões (Opcional)")

  caminho_img_temp = None
  if foto_buffer is not None:
    imagem = Image.open(foto_buffer)
    if imagem.mode in ("RGBA", "P"):
      imagem = imagem.convert("RGB")
    caminho_img_temp = os.path.join(
        PASTA_FOTOS_PENDENTES,
        f"temp_foto_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg",
    )
    imagem.save(caminho_img_temp, "JPEG")
    st.success("📸 Foto capturada e convertida com sucesso!")


  submitted = st.form_submit_button("🚀 SUBMETER MULTI-CARTÃO TERAPÊUTICO")

# --- PROCESSAMENTO DO FORMULÁRIO ---
if submitted:
  if (
      not nome_paciente.strip()
      or not distrito.strip()
      or not nome_responsavel.strip()
      or not unidade_sanitaria.strip()
  ):
    st.error("⚠️ Preencha todos os campos obrigatórios marcados com (*).")
  else:
    idade_anos, total_meses = calcular_idade_detalhada(data_nascimento)
    status, gravidade, imc = diagnosticar_nutricao_completo(
        idade_anos, total_meses, peso, estatura, perimetro_braquial, edema
    )

    # Chamada atualizada passando a província E o distrito
    recomendacao = obter_recomendacao_detalhada(
        provincia, distrito, status, idade_anos
    )
    data_hora_atual = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    meds_rotina_lista = []
    if med_acido_folico:
      meds_rotina_lista.append("Ác. Fólico")
    if med_antibiotico1:
      meds_rotina_lista.append(med_antibiotico1)
    if med_antibiotico2:
      meds_rotina_lista.append(med_antibiotico2)
    meds_rotina_str = (
        ", ".join(meds_rotina_lista) if meds_rotina_lista else "Nenhum"
    )

    dieta_str = (
        f"{fase_dieta} | Qtd: {qtd_tomada}"
        + (" | ATPU" if atpu == "Sim" else "")
    )
    complicacoes_str = ", ".join(complicacoes) if complicacoes else "Nenhuma"

    st.markdown("---")
    st.subheader("📋 Diagnóstico e Resumo Clínico MISAU")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Idade", f"{idade_anos} Anos ({total_meses} Meses)")
    m2.metric("IMC / Escore Z", f"{imc} kg/m²")
    m3.metric("PB", f"{perimetro_braquial} cm")
    m4.metric("Nível de Risco", gravidade)

    if "Grave" in gravidade or "Gravíssimo" in gravidade:
      st.markdown(
          "<div class='status-alert-grave'>"
          f"🚨 DIAGNÓSTICO: {status}<br>Classificação: {gravidade} | Edema:"
          f" {edema}</div>",
          unsafe_allow_html=True,
      )
    elif "Moderado" in gravidade or "Alerta" in gravidade:
      st.markdown(
          "<div class='status-alert-mod'>"
          f"🟡 DIAGNÓSTICO: {status}<br>Classificação: {gravidade} | Edema:"
          f" {edema}</div>",
          unsafe_allow_html=True,
      )
    else:
      st.markdown(
          "<div class='status-alert-ok'>"
          f"🟢 DIAGNÓSTICO: {status}<br>Classificação: {gravidade}</div>",
          unsafe_allow_html=True,
      )

    st.info(
        f"💡 **Recomendação Alimentar e Conduta Regional ({distrito}, {provincia}):**\n\n{recomendacao}"
    )

    nome_pdf_local = os.path.join(
        PASTA_PDFS_PENDENTES,
        f"MultiCartao_{nome_paciente.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
    )

    dados_dict = {
        "data_hora": data_hora_atual,
        "num_ordem": num_ordem,
        "nid": nid,
        "paciente": nome_paciente,
        "data_nasc": data_nascimento.strftime("%d/%m/%Y"),
        "idade_anos": idade_anos,
        "sexo": sexo,
        "responsavel": nome_responsavel,
        "telefone": telefone,
        "provincia": provincia,
        "distrito": distrito,
        "us": unidade_sanitaria,
        "num_quarto": num_quarto,
        "num_cama": num_cama,
        "endereco": bairro,
        "distancia_us": distancia_us,
        "data_internamento": data_internamento.strftime("%d/%m/%Y"),
        "tipo_admissao": tipo_admissao,
        "peso": peso,
        "altura": estatura,
        "peso_alvo": peso_alvo,
        "pe_dp": pe_dp,
        "pb": perimetro_braquial,
        "edema": edema,
        "imc": imc,
        "status": status,
        "gravidade": gravidade,
        "teste_hiv": teste_hiv,
        "teste_tb": teste_tb,
        "glicemia": glicemia,
        "teste_malaria": teste_malaria,
        "complicacoes": complicacoes_str,
        "temp_ax_rec": temp_ax_rec,
        "desidratacao": desidratacao,
        "vomito": vomito,
        "meds_rotina": meds_rotina_str,
        "dieta_terapeutica": dieta_str,
        "recomendacao": recomendacao,
        "tecnico": st.session_state["nome_completo"],
    }

    try:
      gerar_pdf_laudo_tecnico(dados_dict, nome_pdf_local, caminho_img_temp)
      if os.path.exists(nome_pdf_local):
        with open(nome_pdf_local, "rb") as file_pdf:
          st.download_button(
              label="📄 Descarregar PDF do Multi-Cartão Terapêutico",
              data=file_pdf,
              file_name=os.path.basename(nome_pdf_local),
              mime="application/pdf",
              type="primary",
          )
    except Exception as e:
      st.error(f"Erro ao gerar o documento PDF: {e}")

    params_db = {
        "dh": data_hora_atual,
        "tu": st.session_state["nome_completo"],
        "np": nome_paciente,
        "dn": data_nascimento.strftime("%d/%m/%Y"),
        "if": f"{idade_anos} anos",
        "sx": sexo,
        "rc": "Não informado",
        "nr": nome_responsavel,
        "tf": telefone,
        "pr": provincia,
        "ds": distrito,
        "br": bairro,
        "ps": float(peso),
        "al": float(estatura),
        "pb": float(perimetro_braquial),
        "pc": 0.0,
        "ed": edema,
        "zs": float(imc),
        "st": status,
        "gr": gravidade,
        "cd": recomendacao,
        "pdf": nome_pdf_local,
    }

    engine = get_db_engine()
    try:
      with engine.begin() as conn:
        conn.execute(
            text("""
                    INSERT INTO triagens (
                        data_hora, tecnico_username, nome_paciente, data_nascimento, idade_formatada,
                        sexo, raca, nome_responsavel, telefone, provincia, distrito, bairro,
                        peso, altura, perimetro_braquial, perimetro_craniano, edema, zscore, status, gravidade, conduta, caminho_pdf
                    ) VALUES (
                        :dh, :tu, :np, :dn, :if, :sx, :rc, :nr, :tf, :pr, :ds, :br, :ps, :al, :pb, :pc, :ed, :zs, :st, :gr, :cd, :pdf
                    )
                """),
            params_db,
        )
      st.success(
          "✅ Multi-Cartão submetido com sucesso! O Relatorio foi"
          " atualizado."
      )
    except Exception as err:
      guardar_pendente_local({"params_db": params_db})
      st.warning(
          f"📶 Erro de conexão com o Supabase ({err}). O registo foi guardado"
          " localmente e será enviado quando houver rede."
      )