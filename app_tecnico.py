import base64
from datetime import datetime, date
import json
import os
import re
import cv2
from fpdf import FPDF
from PIL import Image
import gspread
import numpy as np
import requests  # Biblioteca adicionada para conectar à API FastAPI
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import streamlit as st

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Multi-Cartão Terapêutico - Técnico de Campo",
    layout="wide",
    page_icon="🩺",
    initial_sidebar_state="expanded"
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

# Garantir que as pastas locais existem dentro do diretório do técnico
os.makedirs(PASTA_PDFS_PENDENTES, exist_ok=True)
os.makedirs(PASTA_FOTOS_PENDENTES, exist_ok=True)

# Constantes Globais
ID_PASTA_GOOGLE_DRIVE = "1ksUFOL3XWDyq91rPbfTJQQmof1WIoBa"
API_URL_DIAGNOSTICAR = "http://127.0.0.1:8000/diagnosticar"

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
    """Remove caracteres fora do intervalo Latin-1 para evitar exceções Unicode no FPDF."""
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

# --- FUNÇÃO DE INTEGRAÇÃO COM A API FASTAPI & SUPABASE ---
def chamar_api_diagnosticar(peso, altura, pb, edema, imc, idade, nome_paciente):
    """Envia os dados antropométricos para a API FastAPI e salva no Supabase."""
    # Mapear valor do edema para número
    edema_valor = 0
    if "+" in str(edema):
        edema_valor = str(edema).count("+")

    payload = {
        "peso": float(peso),
        "altura": float(altura),
        "pb": float(pb),
        "edema": edema_valor,
        "imc": float(imc),
        "idade": float(idade),
        "nome_paciente": str(nome_paciente)
    }

    try:
        response = requests.post(API_URL_DIAGNOSTICAR, json=payload, timeout=5)
        if response.status_code == 200:
            dados = response.json()
            return True, dados.get("diagnostico", "Diagnóstico Concluído"), dados.get("mensagem", "")
        else:
            return False, None, f"Erro na API (Código {response.status_code})"
    except Exception as e:
        return False, None, f"Falha ao conectar à API local: {e}"

# --- OPERAÇÕES DE FICHEIROS LOCALIZADOS NA PASTA DO TÉCNICO ---
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

def conectar_base_dados_nuvem():
    caminho_credenciais = os.path.join(DIRETORIO_TECNICO, "credenciais.json")
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(caminho_credenciais, scope)
    client = gspread.authorize(creds)
    return client.open("Triagem_Nutricional")

def upload_ficheiro_para_drive(caminho_ficheiro, nome_no_drive, mime_type="application/pdf"):
    caminho_credenciais = os.path.join(DIRETORIO_TECNICO, "credenciais.json")
    scope = ["https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(caminho_credenciais, scope)
    drive_service = build("drive", "v3", credentials=creds)

    metadata_ficheiro = {"name": nome_no_drive, "parents": [ID_PASTA_GOOGLE_DRIVE]}
    media = MediaFileUpload(caminho_ficheiro, mimetype=mime_type)

    ficheiro = drive_service.files().create(
        body=metadata_ficheiro, media_body=media, fields='id, webViewLink',
        supportsAllDrives=True, supportsTeamDrives=True
    ).execute()

    permissao = {"type": "anyone", "role": "reader"}
    drive_service.permissions().create(fileId=ficheiro.get("id"), body=permissao, supportsAllDrives=True).execute()

    return ficheiro.get("webViewLink")

def sincronizar_registos_pendentes():
    pendentes = carregar_pendentes_locais()
    if not pendentes:
        return True, "Não existem registos pendentes por sincronizar."

    try:
        doc = conectar_base_dados_nuvem()
        sheet = doc.sheet1
        registos_mantidos = []

        for registro in pendentes:
            caminho_pdf = registro.get("caminho_pdf")
            caminho_foto = registro.get("caminho_foto")
            linha = registro.get("linha_dados")

            link_pdf = registro.get("link_pdf", "Sem PDF")
            link_foto = registro.get("link_foto", "Sem Foto")

            if (not link_pdf or link_pdf == "Pendente Upload") and caminho_pdf and os.path.exists(caminho_pdf):
                try:
                    link_pdf = upload_ficheiro_para_drive(caminho_pdf, os.path.basename(caminho_pdf), "application/pdf")
                except Exception:
                    pass

            if (not link_foto or link_foto == "Pendente Upload") and caminho_foto and os.path.exists(caminho_foto):
                try:
                    link_foto = upload_ficheiro_para_drive(caminho_foto, os.path.basename(caminho_foto), "image/jpeg")
                except Exception:
                    pass

            if len(linha) >= 17:
                linha[15] = link_pdf
                linha[16] = link_foto

            try:
                sheet.append_row(linha)
            except Exception:
                registro["link_pdf"] = link_pdf
                registro["link_foto"] = link_foto
                registos_mantidos.append(registro)

        if not registos_mantidos:
            limpar_pendentes_locais()
            return True, "🟢 Registos sincronizados com sucesso!"
        else:
            with open(FICHEIRO_PENDENTES, "w", encoding="utf-8") as f:
                json.dump(registos_mantidos, f, ensure_ascii=False, indent=4)
            return False, "⚠️ Alguns registos continuam salvos localmente para novo envio."

    except Exception as e:
        return False, f"⚠ Falha ao conectar ao servidor central: {e}"

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

    # Identificação
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

    # Antropometria
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

    # Exames e Controlo
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

    # Conduta Regional
    pdf.set_font("Arial", "B", 11)
    pdf.cell(190, 6, txt="4. RECOMENDAÇÃO NUTRICIONAL REGIONAL", ln=True)
    pdf.set_font("Arial", "", 9)
    recomendacao_limpa = limpar_emojis_para_pdf(dados_dict['recomendacao'])
    pdf.multi_cell(190, 5, txt=recomendacao_limpa)
    pdf.ln(4)

    if caminho_foto and os.path.exists(caminho_foto):
        try:
            pdf.set_font("Arial", "B", 10)
            pdf.cell(190, 6, txt="REGISTO FOTOGRÁFICO:", ln=True)
            pdf.image(caminho_foto, x=10, y=pdf.get_y() + 2, w=50)
        except Exception:
            pass

    pdf.output(caminho_saida_pdf)

# --- INTERFACE DO TÉCNICO DE CAMPO ---
st.markdown("<div class='main-header'>🩺 Triagem Nutricional</div>", unsafe_allow_html=True)
st.markdown("<div class='sub-header'>Múlti-Cartão de Tratamento Terapêutico para Desnutrição (MISAU)</div>", unsafe_allow_html=True)

# --- SIDEBAR: MENU DO TÉCNICO ---
st.sidebar.title("📌 Menu do Técnico")

# 1. USERNAME E PASSWORD EM PRIMEIRO LUGAR
st.sidebar.subheader("🔑 Autenticação do Técnico")
tecnico_username = st.sidebar.text_input("Username / Utilizador", key="menu_username")
tecnico_password = st.sidebar.text_input("Password / Palavra-passe", type="password", key="menu_password")

st.sidebar.markdown("---")

# Informações de rede e sincronização
st.sidebar.info("Modo **100% Offline** ativo. Sincronize quando tiver rede.")

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
        data_nascimento = st.date_input("Data de Nascimento *", value=date(1926, 1, 1), max_value=date.today())
        sexo = st.radio("Sexo *", ["Masculino", "Feminino"], horizontal=True)

    with col2:
        nome_responsavel = st.text_input("Nome do Acompanhante / Responsável *")
        telefone = st.text_input("Contacto Telefónico *")
        provincia = st.selectbox("Província *", PROVINCIAS)
        distrito = st.text_input("Distrito *")
        unidade_sanitaria = st.text_input("Unidade Sanitária (US) *")

    with col3:
        num_quarto = st.text_input("N.º do Quarto")
        num_cama = st.text_input("N.º da Cama")
        endereco = st.text_input("Endereço / Bairro *")
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
    nome_tecnico = st.text_input("Nome / Código do Técnico Responsável *", value=tecnico_username if tecnico_username else "")
    st.markdown("</div>", unsafe_allow_html=True)

    # --- SEÇÃO 8: TIRAR FOTO DO PACIENTE E CONVERTER FOTO (EM ÚLTIMO LUGAR NO FORMULÁRIO) ---
    st.markdown("<div class='section-card'>", unsafe_allow_html=True)
    st.subheader("📷 Tirar Foto do Paciente e Converter Foto")
    foto_buffer = st.camera_input("Capturar Imagem do Paciente / Lesões (Opcional)")

    caminho_img_temp = None
    if foto_buffer is not None:
        imagem = Image.open(foto_buffer)
        if imagem.mode in ("RGBA", "P"):
            imagem = imagem.convert("RGB")
        
        caminho_img_temp = os.path.join(PASTA_FOTOS_PENDENTES, f"temp_foto_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
        imagem.save(caminho_img_temp, "JPEG")
        st.success("📸 Foto capturada e convertida com sucesso!")
    st.markdown("</div>", unsafe_allow_html=True)

    submitted = st.form_submit_button("🚀 SUBMETER MULTI-CARTÃO TERAPÊUTICO")

# --- PROCESSAMENTO DO FORMULÁRIO ---
if submitted:
    if not nome_paciente.strip() or not nome_tecnico.strip() or not distrito.strip() or not nome_responsavel.strip() or not unidade_sanitaria.strip():
        st.error("⚠️ Preencha todos os campos obrigatórios marcados com (*).")
    else:
        idade_anos, total_meses = calcular_idade_detalhada(data_nascimento)
        status, gravidade, imc = diagnosticar_nutricao_completo(idade_anos, total_meses, peso, estatura, perimetro_braquial, edema)

        # --- INTEGRAÇÃO COM A API FASTAPI + SUPABASE ---
        sucesso_api, diag_ia, msg_supabase = chamar_api_diagnosticar(
            peso=peso, altura=estatura, pb=perimetro_braquial, edema=edema, imc=imc, idade=idade_anos, nome_paciente=nome_paciente
        )

        if sucesso_api and diag_ia:
            status = diag_ia  # Atualiza com a resposta oficial da IA FastAPI
            st.toast(f"✅ {msg_supabase}", icon="💾")

        recomendacao = obter_recomendacao_detalhada(provincia, status, idade_anos)
        data_hora_atual = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        # Organizar resumos dos medicamentos e exames
        meds_rotina_lista = []
        if med_acido_folico: meds_rotina_lista.append("Ác. Fólico")
        if med_antibiotico1: meds_rotina_lista.append(med_antibiotico1)
        if med_antibiotico2: meds_rotina_lista.append(med_antibiotico2)
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

        # Gerar PDF do Laudo
        nome_pdf_local = os.path.join(PASTA_PDFS_PENDENTES, f"MultiCartao_{nome_paciente.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf")

        dados_dict = {
            "data_hora": data_hora_atual, "num_ordem": num_ordem, "nid": nid, "paciente": nome_paciente,
            "data_nasc": data_nascimento.strftime("%d/%m/%Y"), "idade_anos": idade_anos, "sexo": sexo,
            "responsavel": nome_responsavel, "telefone": telefone, "provincia": provincia, "distrito": distrito,
            "us": unidade_sanitaria, "num_quarto": num_quarto, "num_cama": num_cama, "endereco": endereco,
            "distancia_us": distancia_us, "data_internamento": data_internamento.strftime("%d/%m/%Y"),
            "tipo_admissao": tipo_admissao, "peso": peso, "altura": estatura, "peso_alvo": peso_alvo,
            "pe_dp": pe_dp, "pb": perimetro_braquial, "edema": edema, "imc": imc, "status": status,
            "gravidade": gravidade, "teste_hiv": teste_hiv, "teste_tb": teste_tb, "glicemia": glicemia,
            "teste_malaria": teste_malaria, "complicacoes": complicacoes_str, "temp_ax_rec": temp_ax_rec,
            "desidratacao": desidratacao, "vomito": vomito, "meds_rotina": meds_rotina_str,
            "dieta_terapeutica": dieta_str, "recomendacao": recomendacao, "tecnico": nome_tecnico
        }

        try:
            gerar_pdf_laudo_tecnico(dados_dict, nome_pdf_local, caminho_img_temp)
            
            # --- BOTÃO PARA FAZER DOWNLOAD DO PDF GERADO ---
            with open(nome_pdf_local, "rb") as file_pdf:
                st.download_button(
                    label="📄 Fazer Download do PDF (Laudo Técnico)",
                    data=file_pdf,
                    file_name=os.path.basename(nome_pdf_local),
                    mime="application/pdf"
                )
        except Exception as e:
            st.error(f"Erro ao gerar o documento PDF: {e}")

        # Preparar dados para o Google Sheets / Sincronização
        linha_dados_sheets = [
            data_hora_atual, nid, nome_paciente, data_nascimento.strftime("%d/%m/%Y"), idade_anos, sexo,
            nome_responsavel, telefone, provincia, distrito, unidade_sanitaria, peso, estatura, imc,
            perimetro_braquial, edema, status, gravidade, tipo_admissao, meds_rotina_str, dieta_str,
            "Pendente Upload", "Pendente Upload"
        ]

        objeto_offline = {
            "linha_dados": linha_dados_sheets,
            "caminho_pdf": nome_pdf_local,
            "caminho_foto": caminho_img_temp,
            "link_pdf": "Pendente Upload",
            "link_foto": "Pendente Upload"
        }

        try:
            link_pdf = upload_ficheiro_para_drive(nome_pdf_local, os.path.basename(nome_pdf_local), "application/pdf")
            linha_dados_sheets[-2] = link_pdf

            if caminho_img_temp and os.path.exists(caminho_img_temp):
                link_foto = upload_ficheiro_para_drive(caminho_img_temp, os.path.basename(caminho_img_temp), "image/jpeg")
                linha_dados_sheets[-1] = link_foto

            doc = conectar_base_dados_nuvem()
            sheet = doc.sheet1
            sheet.append_row(linha_dados_sheets)
            sincronizar_registos_pendentes()
            st.success("✅ Multi-Cartão Terapêutico enviado e sincronizado com sucesso!")
        except Exception:
            guardar_pendente_local(objeto_offline)
            st.warning("📶 Gravado offline no dispositivo. Será sincronizado com a nuvem assim que houver rede.")