from datetime import datetime, date
import json
import os
import re
import cv2
from fpdf import FPDF
from PIL import Image, ImageOps
import numpy as np
import requests
import streamlit as st
from sqlalchemy import create_engine, text

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Triagem Nutricional",
    layout="wide",
    page_icon="🩺",
    initial_sidebar_state="expanded"
)

# Estilização CSS com Título Azul e Personalizações
st.markdown(
    """
    <style>
    .main-header { font-size: 2.2rem; font-weight: 800; color: #1F77B4; margin-bottom: 0.2rem; text-align: center; }
    .sub-header { font-size: 1.05rem; color: #4B5563; margin-bottom: 1.5rem; text-align: center; }
    .section-card { background-color: #F8FAFC; border: 1px solid #E2E8F0; padding: 1.5rem; border-radius: 12px; margin-bottom: 1.5rem; }
    .status-alert-grave { background-color: #FEE2E2; color: #991B1B; padding: 1rem; border-radius: 8px; font-weight: bold; }
    .status-alert-mod { background-color: #FEF3C7; color: #92400E; padding: 1rem; border-radius: 8px; font-weight: bold; }
    .status-alert-ok { background-color: #D1FAE5; color: #065F46; padding: 1rem; border-radius: 8px; font-weight: bold; }
    .stButton>button { width: 100%; font-weight: bold; height: 3rem; background-color: #1F77B4; color: white; border-radius: 8px; }
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
    st.markdown("<div class='main-header'>🩺 Triagem Nutricional</div>", unsafe_allow_html=True)
    st.markdown("<div class='sub-header'>Múlti-Cartão de Tratamento Terapêutico (MISAU) - Acesso Restrito</div>", unsafe_allow_html=True)
    
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
                    try:
                        with engine.connect() as conn:
                            query = text("SELECT * FROM usuarios WHERE username = :u AND password = :p AND lower(tipo) LIKE '%tecnico%'")
                            resultado = conn.execute(query, {"u": user_input, "p": pass_input}).fetchone()
                            
                            if resultado:
                                st.session_state["autenticado"] = True
                                st.session_state["usuario_atual"] = user_input
                                
                                res_dict = dict(resultado._mapping)
                                st.session_state["nome_completo"] = res_dict.get("nome", user_input)
                                prov = res_dict.get("provincia", "")
                                dist = res_dict.get("distrito", "")
                                
                                st.session_state["provincia_tec"] = prov if prov else "Nampula"
                                st.session_state["distrito_tec"] = dist if dist else ""
                                
                                st.success("Login efetuado com sucesso! A carregar painel...")
                                st.rerun()
                            else:
                                st.error("Acesso negado: Utilizador, password incorretos ou conta sem privilégios de TÉCNICO.")
                    except Exception as e:
                        st.error(f"Erro ao conectar com a base de dados: {e}")
    st.stop()

# ==============================================================================
# PAINEL COMPLETO DO TÉCNICO AUTENTICADO
# ==============================================================================

PROVINCIAS = [
    "Niassa", "Cabo Delgado", "Nampula", "Zambézia", "Tete", 
    "Manica", "Sofala", "Inhambane", "Gaza", "Maputo Província", "Maputo Cidade"
]

ALIMENTOS_REGIONAIS = {
    "Norte": {
        "provincias": ["Nampula", "Cabo Delgado", "Niassa"],
        "alimentos": "Matapa de folha de mandioca com amendoim, peixe seco/fresco, papas de mexoeira ou milho enriquecidas com gergelim, feijão-nhemba e mandioca cozida.",
        "papas_enriquecidas": "Papas de mexoeira com pó de amendoim torrado e gotas de limão."
    },
    "Centro": {
        "provincias": ["Zambézia", "Tete", "Manica", "Sofala"],
        "alimentos": "Papas de mapira/mexoeira com pó de amendoim, folha de abóbora (m'fumo), peixe do rio (carpa/tilápia), feijão jugo e batata-doce de polpa alaranjada.",
        "papas_enriquecidas": "Papas de mapira com farinha de castanha ou pó de feijão torrado."
    },
    "Sul": {
        "provincias": ["Inhambane", "Gaza", "Maputo Província", "Maputo Cidade"],
        "alimentos": "Matapa de cacana ou couve com amendoim/castanha de caju, peixe do mar, mandioca, feijão-nhemba, abóbora e frutas da época (manga, maçala, cajus).",
        "papas_enriquecidas": "Papas de milho enriquecidas com massa de amendoim e puré de batata-doce."
    },
}

def limpar_emojis_para_pdf(texto: str) -> str:
    if not texto:
        return ""
    return re.sub(r'[^\x00-\xFF]', '', texto)

def obter_recomendacao_detalhada(provincia, status_diagnostico, idade_anos):
    regiao_encontrada = ALIMENTOS_REGIONAIS["Centro"]
    for reg, dados in ALIMENTOS_REGIONAIS.items():
        if provincia in dados["provincias"]:
            regiao_encontrada = dados
            break

    alimentos = regiao_encontrada["alimentos"]
    papas = regiao_encontrada["papas_enriquecidas"]

    if "Grave" in status_diagnostico or "Kwashiorkor" in status_diagnostico:
        if idade_anos <= 5:
            return f"🚨 URGENTE: ENCAMINHAR IMEDIATAMENTE AO CENTRO DE SAÚDE (US) / TAPE!\n- Iniciar formulação de transição conforme protocolo do MISAU.\n- Dieta complementar recomendada no apoio: {papas}"
        else:
            return f"🚨 URGENTE: ENCAMINHAR PARA AVALIAÇÃO CLÍNICA!\n- Reforço hipercalórico e hiperproteico imediato com: {alimentos}"
    
    elif "Moderad" in status_diagnostico or "Baixo Peso" in status_diagnostico:
        if idade_anos <= 5:
            return f"🟡 RECOMENDAÇÃO: Suplementação nutricional e acompanhamento quinzenal.\n- Alimentação recomendada: {papas}\n- Adicionar vegetais folhosos e proteínas locais."
        else:
            return f"🟡 RECOMENDAÇÃO: Aumentar densidade calórica das refeições diárias.\n- Consumo diário recomendado: {alimentos}"

    elif "Sobrepeso" in status_diagnostico or "Obesidade" in status_diagnostico:
        return f"🟠 RECOMENDAÇÃO: Reeducação alimentar e prática de atividade física.\n- Reduzir açúcares refinados, óleos e fritos.\n- Priorizar vegetais locais, mandioca cozida, peixe grelhado e frutas frescas da região."

    return f"🟢 RECOMENDAÇÃO: Manter alimentação equilibrada e variada baseada em produtos locais ({alimentos})."

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

def diagnosticar_nutricao_completo(idade_anos, total_meses, peso, altura, pb, edema):
    altura_m = altura / 100.0 if altura > 3.0 else altura
    imc = round(peso / (altura_m**2), 2) if altura_m > 0 else 0.0

    if total_meses <= 60:
        if edema in ["+", "++", "+++"]:
            return "Desnutrição Aguda Grave (Kwashiorkor / Edema Bilateral)", "Nível 3 - Gravíssimo", imc
        if 0.0 < pb < 11.5:
            return "Desnutrição Aguda Grave (DAG) por PB", "Nível 3 - Grave", imc
        elif 11.5 <= pb < 12.5:
            return "Desnutrição Aguda Moderada (DAM) por PB", "Nível 2 - Moderado", imc
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
                conn.execute(text("""
                    INSERT INTO triagens (
                        data_hora, tecnico_username, nome_paciente, data_nascimento, idade_formatada,
                        sexo, raca, nome_responsavel, telefone, provincia, distrito, bairro,
                        peso, altura, perimetro_braquial, perimetro_craniano, edema, zscore, status, gravidade, conduta, caminho_pdf
                    ) VALUES (
                        :dh, :tu, :np, :dn, :if, :sx, :rc, :nr, :tf, :pr, :ds, :br, :ps, :al, :pb, :pc, :ed, :zs, :st, :gr, :cd, :pdf
                    )
                """), params)
        except Exception:
            pendentes_mantidos.append(registro)

    if not pendentes_mantidos:
        limpar_pendentes_locais()
        return True, "🟢 Registos sincronizados com sucesso para o Supabase!"
    else:
        with open(FICHEIRO_PENDENTES, "w", encoding="utf-8") as f:
            json.dump(pendentes_mantidos, f, ensure_ascii=False, indent=4)
        return False, "⚠️ Alguns registos continuam salvos localmente para novo envio."

def gerar_pdf_laudo_tecnico(dados_dict, caminho_saida_pdf, caminho_foto=None):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    pdf.set_font("Arial", "B", 14)
    pdf.cell(190, 8, txt="REPÚBLICA DE MOÇAMBIQUE - SERVIÇO NACIONAL DE SAÚDE", ln=True, align="C")
    pdf.set_font("Arial", "B", 12)
    pdf.cell(190, 6, txt="MÚLTI-CARTÃO DE TRATAMENTO TERAPÊUTICO PARA DESNUTRIÇÃO", ln=True, align="C")
    pdf.set_font("Arial", "I", 9)
    pdf.cell(190, 5, txt=f"Emissão: {dados_dict['data_hora']} | Técnico: {limpar_emojis_para_pdf(dados_dict['tecnico'])}", ln=True, align="C")
    pdf.ln(4)

    pdf.set_line_width(0.5)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(4)

    pdf.set_font("Arial", "B", 11)
    pdf.cell(190, 6, txt="1. IDENTIFICAÇÃO E LOCALIZAÇÃO DO PACIENTE", ln=True)
    pdf.set_font("Arial", "", 9)
    pdf.cell(95, 5, txt=f"N.º de Ordem Mensal: {dados_dict['num_ordem']}", ln=False)
    pdf.cell(95, 5, txt=f"NID: {dados_dict['nid']}", ln=True)
    pdf.cell(190, 5, txt=f"Nome do Doente: {limpar_emojis_para_pdf(dados_dict['paciente'])}", ln=True)
    pdf.cell(95, 5, txt=f"Data Nasc.: {dados_dict['data_nasc']} ({dados_dict['idade_anos']} Anos)", ln=False)
    pdf.cell(95, 5, txt=f"Sexo: {dados_dict['sexo']}", ln=True)
    pdf.cell(95, 5, txt=f"Acompanhante: {limpar_emojis_para_pdf(dados_dict['responsavel'])}", ln=False)
    pdf.cell(95, 5, txt=f"Contacto: {dados_dict['telefone']}", ln=True)
    pdf.cell(95, 5, txt=f"Província: {dados_dict['provincia']} | Dist: {dados_dict['distrito']}", ln=False)
    pdf.cell(95, 5, txt=f"Unidade Sanitária (US): {dados_dict['us']}", ln=True)
    pdf.cell(95, 5, txt=f"Nº Quarto: {dados_dict['num_quarto']} | Nº Cama: {dados_dict['num_cama']}", ln=False)
    pdf.cell(95, 5, txt=f"Distância à US: {dados_dict['distancia_us']}", ln=True)
    pdf.cell(95, 5, txt=f"Data Internamento: {dados_dict['data_internamento']}", ln=False)
    pdf.cell(95, 5, txt=f"Tipo Admissão: {dados_dict['tipo_admissao']}", ln=True)
    pdf.ln(3)

    pdf.set_font("Arial", "B", 11)
    pdf.cell(190, 6, txt="2. MAPA ANTROPOMÉTRICO E DIAGNÓSTICO", ln=True)
    pdf.set_font("Arial", "", 9)
    pdf.cell(63, 5, txt=f"Peso: {dados_dict['peso']} kg", ln=False)
    pdf.cell(63, 5, txt=f"Estatura: {dados_dict['altura']} cm", ln=False)
    pdf.cell(64, 5, txt=f"Peso Alvo: {dados_dict['peso_alvo']} kg", ln=True)
    pdf.cell(63, 5, txt=f"P/E (D/P): {dados_dict['pe_dp']}", ln=False)
    pdf.cell(63, 5, txt=f"PB: {dados_dict['pb']} cm", ln=False)
    pdf.cell(64, 5, txt=f"Edema: {dados_dict['edema']}", ln=True)
    pdf.cell(95, 5, txt=f"IMC/Idade: {dados_dict['imc']}", ln=False)
    pdf.cell(95, 5, txt=f"Diagnóstico: {limpar_emojis_para_pdf(dados_dict['status'])}", ln=True)
    pdf.ln(3)

    pdf.set_font("Arial", "B", 11)
    pdf.cell(190, 6, txt="3. TESTES, CONTROLO CLÍNICO E TRATAMENTO", ln=True)
    pdf.set_font("Arial", "", 9)
    pdf.cell(95, 5, txt=f"HIV: {dados_dict['teste_hiv']} | TB: {dados_dict['teste_tb']}", ln=False)
    pdf.cell(95, 5, txt=f"Malária: {dados_dict['teste_malaria']} | Glicemia: {dados_dict['glicemia']}", ln=True)
    pdf.cell(190, 5, txt=f"Complicações: {limpar_emojis_para_pdf(dados_dict['complicacoes'])}", ln=True)
    pdf.cell(95, 5, txt=f"Febre/Temp: {dados_dict['temp_ax_rec']}", ln=False)
    pdf.cell(95, 5, txt=f"Desidratação: {dados_dict['desidratacao']} | Vómito: {dados_dict['vomito']}", ln=True)
    pdf.cell(190, 5, txt=f"Medicamentos de Rotina: {limpar_emojis_para_pdf(dados_dict['meds_rotina'])}", ln=True)
    pdf.cell(190, 5, txt=f"Dieta Terapêutica: {limpar_emojis_para_pdf(dados_dict['dieta_terapeutica'])}", ln=True)
    pdf.ln(3)

    pdf.set_font("Arial", "B", 11)
    pdf.cell(190, 6, txt="4. RECOMENDAÇÃO NUTRICIONAL REGIONAL", ln=True)
    pdf.set_font("Arial", "", 9)
    recomendacao_limpa = limpar_emojis_para_pdf(dados_dict['recomendacao'])
    pdf.multi_cell(190, 5, txt=recomendacao_limpa)
    pdf.ln(4)

    # Inclusão da Foto Real e da Imagem de Visão Computacional no PDF
    if caminho_foto and os.path.exists(caminho_foto):
        try:
            pdf.set_font("Arial", "B", 10)
            pdf.cell(190, 6, txt="REGISTO FOTOGRÁFICO E ANÁLISE DE VISÃO COMPUTACIONAL:", ln=True)
            
            # Gerar imagem processada de visão computacional (ex: escala de cinza e inversão/contornos)
            img_original = Image.open(caminho_foto)
            img_proc = ImageOps.invert(img_original.convert("L"))
            caminho_foto_proc = caminho_foto.replace(".jpg", "_proc.jpg")
            img_proc.save(caminho_foto_proc, "JPEG")
            
            y_pos = pdf.get_y() + 2
            # Insere a Foto Real à esquerda
            pdf.image(caminho_foto, x=10, y=y_pos, w=85)
            # Insere a Imagem de Visão Computacional à direita
            pdf.image(caminho_foto_proc, x=105, y=y_pos, w=85)
            
            pdf.ln(65)
        except Exception:
            pass

    pdf.output(caminho_saida_pdf)

# --- SIDEBAR COM DADOS DO TÉCNICO AUTENTICADO ---
st.sidebar.title("📌 Menu do Técnico")
st.sidebar.info(f"👤 **{st.session_state['nome_completo']}**\n\n📍 **Jurisdição:** {st.session_state['provincia_tec']} / {st.session_state['distrito_tec'] if st.session_state['distrito_tec'] else 'Geral'}")

if st.sidebar.button("🚪 Terminar Sessão"):
    st.session_state["autenticado"] = False
    st.session_state["usuario_atual"] = ""
    st.session_state["nome_completo"] = ""
    st.session_state["provincia_tec"] = ""
    st.session_state["distrito_tec"] = ""
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.info("Modo **Sincronização Direta Supabase** ativo.")

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

# --- INTERFACE DO TÉCNICO DE CAMPO ---
st.markdown("<div class='main-header'>🩺 Triagem Nutricional</div>", unsafe_allow_html=True)
st.markdown(f"<div class='sub-header'>Múlti-Cartão de Tratamento Terapêutico para Desnutrição (MISAU) | Técnico: <b>{st.session_state['nome_completo']}</b></div>", unsafe_allow_html=True)

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
        data_nascimento = st.date_input("Data de Nascimento *", value=date(2020, 1, 1), max_value=date.today())
        sexo = st.radio("Sexo *", ["Masculino", "Feminino"], horizontal=True)

    with col2:
        nome_responsavel = st.text_input("Nome do Acompanhante / Responsável *")
        telefone = st.text_input("Contacto Telefónico *")
        prov_index = PROVINCIAS.index(st.session_state['provincia_tec']) if st.session_state['provincia_tec'] in PROVINCIAS else 0
        provincia = st.selectbox("Província *", PROVINCIAS, index=prov_index)
        distrito = st.text_input("Distrito *", value=st.session_state['distrito_tec'])
        unidade_sanitaria = st.text_input("Unidade Sanitária (US) *")

    with col3:
        num_quarto = st.text_input("N.º do Quarto")
        num_cama = st.text_input("N.º da Cama")
        bairro = st.text_input("Endereço / Bairro *")
        distancia_us = st.text_input("Distância da casa à US (ex: 5 km)")
        data_internamento = st.date_input("Data de Internamento", value=date.today())

    st.markdown("---")
    st.markdown("**Informações de Admissão e Alimentação do Doente:**")
    col_adm1, col_adm2, col_adm3 = st.columns(3)
    with col_adm1:
        tipo_admissao = st.selectbox(
            "Tipo de Caso (Admissão)",
            ["Caso Novo", "Referido do TDA", "Transferido de outro sector", "Abandono que retorna"]
        )
    with col_adm2:
        aleitamento_materno = st.radio("Aleitamento Materno?", ["Sim", "Não"], horizontal=True)
    with col_adm3:
        alimentacao_complementar = st.radio("Alimentação Complementar?", ["Sim", "Não"], horizontal=True)

    st.markdown("</div>", unsafe_allow_html=True)

    # --- SEÇÃO 2: AVALIAÇÃO ANTROPOMÉTRICA & DIAGNÓSTICO ---
    st.markdown("<div class='section-card'>", unsafe_allow_html=True)
    st.subheader("2. Mapa Antropométrico & Diagnóstico")
    
    col_ant1, col_ant2, col_ant3 = st.columns(3)
    with col_ant1:
        peso = st.number_input("Peso (kg) *", min_value=0.5, max_value=250.0, value=12.0, step=0.1)
        estatura = st.number_input("Estatura / Altura (cm) *", min_value=30.0, max_value=230.0, value=80.0, step=0.5)
        peso_alvo = st.number_input("Peso Alvo (kg)", min_value=0.0, max_value=250.0, value=14.0, step=0.1)

    with col_ant2:
        perimetro_braquial = st.number_input("PB - Perímetro Braquial (cm)", min_value=0.0, max_value=60.0, value=14.0, step=0.1)
        pe_dp = st.selectbox("P/E - Peso/Estatura (D/P)", ["Normal", "Desvio Padrão -1", "Desvio Padrão -2", "Desvio Padrão -3", "< -3 SD"])
        edema = st.selectbox("Edema Bilateral *", ["0 (Ausente)", "+ (Leve)", "++ (Moderado)", "+++ (Grave)"])

    with col_ant3:
        st.markdown("**Critérios Diagnósticos MISAU:**")
        st.info("O sistema calcula automaticamente o IMC e a gravidade com base no peso, altura, PB e Edema.")

    st.markdown("</div>", unsafe_allow_html=True)

    # --- SEÇÃO 3: TESTES LABORATORIAIS E CLÍNICOS ---
    st.markdown("<div class='section-card'>", unsafe_allow_html=True)
    st.subheader("3. Resultados dos Testes Clínicos / Laboratoriais")

    col_t1, col_t2, col_t3 = st.columns(3)
    with col_t1:
        teste_hiv = st.selectbox("Teste HIV", ["Não Realizado", "Negativo", "Positivo", "Indeterminado"])
        teste_tb = st.selectbox("Teste TB (Tuberculose)", ["Não Realizado", "Negativo", "Positivo", "Suspeito"])

    with col_t2:
        glicemia = st.text_input("Glicemia (mg/dL)", value="Normal")
        teste_malaria = st.selectbox("Teste de Malária", ["Não Realizado", "Negativo", "Positivo (TDR)", "Positivo (Lâmina)"])

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
                ["Nenhuma", "Hipoglicemia", "Hipotermia", "Infeção Grave", "Anemia Severa", "Lesões de Pele", "Anorexia"]
            )
            desidratacao = st.selectbox("Desidratação", ["0 (Ausente)", "+ (Ligeira)", "++ (Moderada)", "+++ (Grave)"])
            vomito = st.radio("Vómito", ["Ausente", "Ligeiro", "Frequente", "Persistente"], horizontal=True)

        with c_ctrl2:
            dejeccoes = st.selectbox("Dejecções (Diarreia)", ["Normais", "+ (1-3/dia)", "++ (4-6/dia)", "+++ (>6/dia ou Líquida)"])
            tosse = st.radio("Tosse Presente?", ["Não", "Sim"], horizontal=True)
            choque_septico = st.radio("Choque Séptico?", ["Não", "Sim"], horizontal=True)

        with c_ctrl3:
            freq_respiratoria = st.text_input("Frequência Respiratoria (rpm)", value="30")
            temp_ax_rec = st.text_input("Temperatura Axilar/Rectal (°C)", value="36.5")
            conjuntivas_palidas = st.radio("Conjuntivas Pálidas?", ["Não", "Sim"], horizontal=True)
            dermatite = st.selectbox("Dermatite", ["0 (Ausente)", "+ (Ligeira)", "++ (Moderada)", "+++ (Extensa)"])
            tamanho_figado = st.text_input("Tamanho do Fígado (cm)", value="Normal")
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
            med_antibiotico1 = st.text_input("Antibiótico 1 (ex: Amoxicilina)", value="Amoxicilina")
            med_antibiotico2 = st.text_input("Antibiótico 2 / Outros", value="")
            med_vitamina_a = st.text_input("Vitamina A (UI)", value="200.000 UI")

            st.markdown("**Medicamentos e Equipamentos Especiais:**")
            med_suplemento_ferro = st.checkbox("Suplemento de Ferro")
            med_antimalarico = st.checkbox("Anti-malárico")
            med_antihelmintico = st.checkbox("Anti-helmíntico (Mebendazol/Albendazol)")
            med_resomal = st.checkbox("ReSoMal (ml)")
            med_fluido_iv = st.checkbox("Fluído IV / Sangue")
            med_sonda_ng = st.checkbox("Uso de Sonda Nasogástrica (NG)")

        with c_med2:
            st.markdown("**Dieta Terapêutica:**")
            fase_dieta = st.selectbox("Fase da Dieta Terapêutica", ["Fase 1 (F-75)", "Transição (F-75/F-100)", "Fase 2 (F-100 / ATPU)", "Reabilitação"])
            atpu = st.radio("ATPU / RUFT (Alimento Terapêutico Pronto a Usar)", ["Não", "Sim"], horizontal=True)
            qtd_tomada = st.select_slider("Quantidade Tomada da Dieta", options=["1/4", "1/2", "3/4", "100%"])
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
    nome_tecnico = st.text_input("Nome / Código do Técnico Responsável *", value=st.session_state["nome_completo"], disabled=True)
    st.markdown("</div>", unsafe_allow_html=True)

    # --- SEÇÃO 8: TIRAR FOTO DO PACIENTE (CÂMERA TRASEIRA AUTOMÁTICA) ---
    st.markdown("<div class='section-card'>", unsafe_allow_html=True)
    st.subheader("📷 Tirar Foto do Paciente")
    
    # facing_mode="environment" força o telemóvel a abrir a câmara traseira
    foto_buffer = st.camera_input("Capturar Imagem do Paciente / Lesões (Opcional)", facing_mode="environment")

    caminho_img_temp = None
    if foto_buffer is not None:
        imagem = Image.open(foto_buffer)
        if imagem.mode in ("RGBA", "P"):
            imagem = imagem.convert("RGB")
        caminho_img_temp = os.path.join(PASTA_FOTOS_PENDENTES, f"temp_foto_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
        imagem.save(caminho_img_temp, "JPEG")
        st.success("📸 Foto real capturada com sucesso! A análise de visão computacional será adicionada automaticamente no PDF.")
    st.markdown("</div>", unsafe_allow_html=True)

    submitted = st.form_submit_button("🚀 SUBMISTER MULTI-CARTÃO TERAPÊUTICO")

# --- PROCESSAMENTO DO FORMULÁRIO ---
if submitted:
    if not nome_paciente.strip() or not distrito.strip() or not nome_responsavel.strip() or not unidade_sanitaria.strip():
        st.error("⚠️ Preencha todos os campos obrigatórios marcados com (*).")
    else:
        idade_anos, total_meses = calcular_idade_detalhada(data_nascimento)
        status, gravidade, imc = diagnosticar_nutricao_completo(idade_anos, total_meses, peso, estatura, perimetro_braquial, edema)

        recomendacao = obter_recomendacao_detalhada(provincia, status, idade_anos)
        data_hora_atual = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        meds_rotina_lista = []
        if med_acido_folico: 
            meds_rotina_lista.append("Ác. Fólico")
        if med_antibiotico1: 
            meds_rotina_lista.append(med_antibiotico1)
        if med_antibiotico2: 
            meds_rotina_lista.append(med_antibiotico2)
        meds_rotina_str = ", ".join(meds_rotina_lista) if meds_rotina_lista else "Nenhum"

        dieta_str = f"{fase_dieta} | Qtd: {qtd_tomada}" + (" | ATPU" if atpu == "Sim" else "")
        complicacoes_str = ", ".join(complicacoes) if complicacoes else "Nenhuma"

        st.markdown("---")
        st.subheader("📋 Diagnóstico e Resumo Clínico MISAU")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Idade", f"{idade_anos} Anos ({total_meses} Meses)")
        m2.metric("IMC / Idade", f"{imc} kg/m²")
        m3.metric("PB", f"{perimetro_braquial} cm")
        m4.metric("Nível de Risco", gravidade)

        if "Grave" in gravidade or "Gravíssimo" in gravidade:
            st.markdown(f"<div class='status-alert-grave'>🚨 DIAGNÓSTICO: {status}<br>Classificação: {gravidade} | Edema: {edema}</div>", unsafe_allow_html=True)
        elif "Moderado" in gravidade or "Alerta" in gravidade:
            st.markdown(f"<div class='status-alert-mod'>🟡 DIAGNÓSTICO: {status}<br>Classificação: {gravidade} | Edema: {edema}</div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='status-alert-ok'>🟢 DIAGNÓSTICO: {status}<br>Classificação: {gravidade}</div>", unsafe_allow_html=True)

        st.info(f"💡 **Recomendação Alimentar Regional ({provincia}):**\n\n{recomendacao}")

        nome_pdf_local = os.path.join(PASTA_PDFS_PENDENTES, f"MultiCartao_{nome_paciente.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf")

        dados_dict = {
            "data_hora": data_hora_atual, "num_ordem": num_ordem, "nid": nid, "paciente": nome_paciente,
            "data_nasc": data_nascimento.strftime("%d/%m/%Y"), "idade_anos": idade_anos, "sexo": sexo,
            "responsavel": nome_responsavel, "telefone": telefone, "provincia": provincia, "distrito": distrito,
            "us": unidade_sanitaria, "num_quarto": num_quarto, "num_cama": num_cama, "endereco": bairro,
            "distancia_us": distancia_us, "data_internamento": data_internamento.strftime("%d/%m/%Y"),
            "tipo_admissao": tipo_admissao, "peso": peso, "altura": estatura, "peso_alvo": peso_alvo,
            "pe_dp": pe_dp, "pb": perimetro_braquial, "edema": edema, "imc": imc, "status": status,
            "gravidade": gravidade, "teste_hiv": teste_hiv, "teste_tb": teste_tb, "glicemia": glicemia,
            "teste_malaria": teste_malaria, "complicacoes": complicacoes_str, "temp_ax_rec": temp_ax_rec,
            "desidratacao": desidratacao, "vomito": vomito, "meds_rotina": meds_rotina_str,
            "dieta_terapeutica": dieta_str, "recomendacao": recomendacao, "tecnico": st.session_state["nome_completo"]
        }

        try:
            gerar_pdf_laudo_tecnico(dados_dict, nome_pdf_local, caminho_img_temp)
            with open(nome_pdf_local, "rb") as file_pdf:
                st.download_button(
                    label="📄 Fazer Download do PDF (Laudo Técnico com Visão Computacional)",
                    data=file_pdf,
                    file_name=os.path.basename(nome_pdf_local),
                    mime="application/pdf"
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
            "pdf": nome_pdf_local
        }

        engine = get_db_engine()
        try:
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO triagens (
                        data_hora, tecnico_username, nome_paciente, data_nascimento, idade_formatada,
                        sexo, raca, nome_responsavel, telefone, provincia, distrito, bairro,
                        peso, altura, perimetro_braquial, perimetro_craniano, edema, zscore, status, gravidade, conduta, caminho_pdf
                    ) VALUES (
                        :dh, :tu, :np, :dn, :if, :sx, :rc, :nr, :tf, :pr, :ds, :br, :ps, :al, :pb, :pc, :ed, :zs, :st, :gr, :cd, :pdf
                    )
                """), params_db)
            st.success("✅ Multi-Cartão submetido com sucesso! Os dados já chegaram ao Supabase e aparecem no painel do gestor.")
        except Exception as err:
            guardar_pendente_local({"params_db": params_db})
            st.warning(f"📶 Erro de conexão com o Supabase ({err}). O registo foi guardado localmente e será enviado quando houver rede.")
