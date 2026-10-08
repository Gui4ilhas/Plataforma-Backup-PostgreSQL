import streamlit as st
import psycopg2
import subprocess
import os
import glob
import zipfile
import shutil
from datetime import datetime, timedelta
from cryptography.fernet import Fernet
import pandas as pd

st.set_page_config(page_title="Plataforma de Backup", page_icon=":material/database:", layout="wide")

st.title(":material/database: Plataforma de Backup")
st.markdown("Gestão de rotinas PostgreSQL (Criptografia, Retenção e Cópia Dupla).")


# LAYOUT > 4 ABAS

tab_exec, tab_config, tab_restore, tab_audit = st.tabs([
    ":material/cloud_upload: Backup", 
    ":material/settings: Configurações", 
    ":material/settings_backup_restore: Restauração", 
    ":material/history: Auditoria"
])

#     ABA 2: CONFIGURAÇÕES
with tab_config:
    st.header(":material/tune: Parâmetros do Sistema")
    col_c1, col_c2 = st.columns(2)
    with col_c1:
        st.subheader(":material/folder: Diretórios e Retenção")
        
        caminho_principal = st.text_input("Diretório Principal (Obrigatório)", placeholder=r"Ex: C:\MeusBackups", value="")
        caminho_copia = st.text_input("Diretório de Cópia (Opcional)", placeholder=r"Ex: D:\CopiaSeguranca", value="")
        tabela_alvo = st.text_input("Tabela para monitorar VACUUM", placeholder="Ex: clientes", value="")

        qtd_reter = st.number_input("Manter quantos backups? (0 = Todos)", min_value=0, value=5)
        
    with col_c2:
        st.subheader(":material/security: Segurança e Opções")
        chk_zip = st.checkbox("Compactar arquivo (ZIP)")
        chk_aes = st.checkbox("Criptografar arquivo (AES-256)")
        
        st.subheader(":material/science: Testes e Manutenção Manual")
        chk_vacuum = st.checkbox("Executar VACUUM simples (Ignora regra automática)")
        chk_vacuum_full = st.checkbox("Executar VACUUM FULL ANALYZE (Ignora regra automática)")
        simular = st.checkbox("Simular data do VACUUM")
        dias_simulados = st.number_input("Dias simulados (-1 = ausência):", min_value=-1, value=-1)
        simular_falha = st.checkbox("Simular Falha Crítica no Processo")

#      ABA 1: BACKUP - EXECUÇÃO
with tab_exec:
    st.header(":material/admin_panel_settings: Credenciais de Conexão")
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1: host = st.text_input("Host/IP", placeholder="Ex: 172.23.16.140", value="")
    with col2: porta = st.text_input("Porta", value="5432")
    with col3: dbname = st.text_input("Nome do Banco", placeholder="Ex: valim_matheus", value="")
    with col4: usuario = st.text_input("Usuário", value="postgres")
    with col5: senha = st.text_input("Senha", type="password", value="")

    if st.button(":material/cable: Testar Conexão", use_container_width=True):
        if not host or not dbname or not senha:
            st.warning("Preencha o Host, Nome do Banco e a Senha antes de testar a conexão.")
        else:
            try:
                conn = psycopg2.connect(host=host, port=porta, dbname=dbname, user=usuario, password=senha)
                st.success("Conexão estabelecida com sucesso!")
                conn.close()
            except Exception as e:
                st.error(f"Erro de conexão: {e}")

    st.markdown("---")

    if st.button(":material/play_arrow: Iniciar Manutenção e Backup", type="primary", use_container_width=True):
        
        # Trava para impedir a execução se não houver pasta de destino configurada
        if not host or not dbname or not senha or not caminho_principal:
            st.warning("Preencha o Host, Banco, Senha e o Diretório Principal nas Configurações antes de iniciar!")
            st.stop()
            
        if not os.path.exists(caminho_principal): os.makedirs(caminho_principal)
        if caminho_copia and not os.path.exists(caminho_copia): os.makedirs(caminho_copia)

        try:
            conn = psycopg2.connect(host=host, port=porta, dbname=dbname, user=usuario, password=senha)
            conn.autocommit = True
            cur = conn.cursor()
            
            if simular_falha:
                raise Exception("FALHA FORÇADA: O disco de destino perdeu a conexão ou está corrompido.")

            # 1. MOTOR DE DECISÃO
            data_ultimo_vacuum = None
            if simular:
                if dias_simulados >= 0: data_ultimo_vacuum = datetime.now() - timedelta(days=dias_simulados)
            else:
                try:
                    cur.execute("SELECT last_vacuum FROM pg_stat_user_tables WHERE relname = %s;", (tabela_alvo,))
                    res = cur.fetchone()
                    data_ultimo_vacuum = res[0] if res else None
                except: pass

            decisao, acao = "Automática", "Nenhuma"
            if chk_vacuum_full:
                decisao, acao = "Manual", "VACUUM FULL ANALYZE"
            elif chk_vacuum:
                decisao, acao = "Manual", "VACUUM"
            else:
                if data_ultimo_vacuum is None: acao = "VACUUM FULL ANALYZE"
                else:
                    dias = (datetime.now() - (data_ultimo_vacuum.replace(tzinfo=None) if data_ultimo_vacuum.tzinfo else data_ultimo_vacuum)).days
                    if dias > 60: acao = "VACUUM FULL ANALYZE"
                    elif 30 <= dias <= 60: acao = "VACUUM"

            if acao != "Nenhuma": 
                cur.execute(acao)
                st.info(f"Manutenção executada: {acao} (Decisão: {decisao})")

            # 2. PG_DUMP
            nome_base = f"backup_{dbname}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            caminho_backup = os.path.join(caminho_principal, f"{nome_base}.backup")
            env = os.environ.copy()
            env['PGPASSWORD'] = senha
            
            # VERSÃO CORRETA DO POSTGRESQL (14, 16 ou 18)
            caminho_pg_dump = r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" 
            
            subprocess.run([caminho_pg_dump, "-h", host, "-p", porta, "-U", usuario, "-F", "c", "-f", caminho_backup, dbname], env=env, check=True)
            
            arquivo_final = caminho_backup
            logs_seguranca = []

            # 3. COMPACTAÇÃO E CRIPTOGRAFIA 
            if chk_zip:
                caminho_zip = os.path.join(caminho_principal, f"{nome_base}.zip")
                with zipfile.ZipFile(caminho_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    zipf.write(caminho_backup, os.path.basename(caminho_backup))
                arquivo_final = caminho_zip
                logs_seguranca.append("ZIP")
                st.success(f"Arquivo compactado gerado: {caminho_zip}")

            if chk_aes:
                chave = Fernet.generate_key()
                fernet = Fernet(chave)
                caminho_aes = caminho_backup + ".aes"
                with open(caminho_backup, 'rb') as f: original = f.read()
                with open(caminho_aes, 'wb') as f: f.write(fernet.encrypt(original))
                arquivo_final = caminho_aes
                logs_seguranca.append("AES")
                st.info(f"Arquivo criptografado gerado: {caminho_aes}")
                st.code(f"Chave AES: {chave.decode()}", language="text")

            # 4. CÓPIA ADICIONAL
            if caminho_copia:
                shutil.copy(arquivo_final, caminho_copia)
                st.success(f"Cópia adicional salva em: {caminho_copia}")

            # 5. RETENÇÃO
            logs_retencao = ""
            if qtd_reter > 0:
                arquivos = sorted(glob.glob(os.path.join(caminho_principal, "backup_*")), key=os.path.getmtime)
                while len(arquivos) > qtd_reter:
                    try:
                        arq_removido = arquivos.pop(0)
                        os.remove(arq_removido)
                        logs_retencao += " Backup antigo excluído."
                        st.warning(f"🧹 Rotina de Retenção: Um backup antigo foi excluído para respeitar o limite de {qtd_reter} arquivos.")
                    except: pass

            # 6. AUDITORIA
            cur.execute("""
                CREATE TABLE IF NOT EXISTS auditoria_backup (
                    id_execucao SERIAL PRIMARY KEY,
                    data_hora_inicio TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    data_hora_fim TIMESTAMP,
                    decisao_manutencao VARCHAR(50),
                    acao_executada VARCHAR(50),
                    status VARCHAR(20),
                    log_detalhado TEXT,
                    caminho_salvo VARCHAR(255)
                );
            """)
            log_final = f"Processo concluído. Opções: {', '.join(logs_seguranca) if logs_seguranca else 'Nenhuma'}. {logs_retencao}"
            cur.execute("""
                INSERT INTO auditoria_backup (data_hora_fim, decisao_manutencao, acao_executada, status, log_detalhado, caminho_salvo)
                VALUES (CURRENT_TIMESTAMP, %s, %s, %s, %s, %s)
            """, (decisao, acao, 'Sucesso', log_final, arquivo_final))
            
            st.success("Processo totalmente finalizado!")
            cur.close(); conn.close()
            
        except Exception as e:
            st.error(f"Erro Crítico Registrado: {e}")
            try:
                cur.execute("""
                    INSERT INTO auditoria_backup (data_hora_fim, decisao_manutencao, acao_executada, status, log_detalhado, caminho_salvo)
                    VALUES (CURRENT_TIMESTAMP, %s, %s, %s, %s, %s)
                """, ('Automática', 'Nenhuma', 'Falha', str(e), 'Nenhum'))
                conn.commit()
            except: pass

#       ABA 3: RESTAURAÇÃO 
with tab_restore:
    st.header(":material/restore: Restauração de Dados")
    st.info("O sistema criará o novo banco de destino e fará a restauração dos dados.")
    
    arquivo_restaurar = st.text_input("Caminho completo do arquivo (.backup)", placeholder=r"Ex: C:\MeusBackups\arquivo.backup", value="")
    banco_destino = st.text_input("Banco de Destino (Para onde os dados vão)", value="Trabalho_CTM_Restore")
    
    if st.button(":material/settings_backup_restore: Executar Restauração", type="primary"):
        if not host or not senha:
            st.warning("Preencha o Host e a Senha na aba 'Backup' antes de proceder com a restauração.")
            st.stop()
            
        if not os.path.exists(arquivo_restaurar):
            st.error("Arquivo não encontrado no sistema. Descriptografe e descompacte o ficheiro antes de restaurar.")
        else:
            try:
                conn_res = psycopg2.connect(host=host, port=porta, dbname="postgres", user=usuario, password=senha)
                conn_res.autocommit = True
                cur_res = conn_res.cursor()
                try:

                    cur_res.execute(f'CREATE DATABASE "{banco_destino}";')
                except Exception as e:

                    if "already exists" not in str(e) and "já existe" not in str(e):
                        st.warning(f"Aviso ao preparar o banco: {e}")
                finally:
                    cur_res.close()
                    conn_res.close()

                env = os.environ.copy()
                env['PGPASSWORD'] = senha 
                
                caminho_pg_restore = r"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe"
                
                comando = [
                    caminho_pg_restore, "-h", host, "-p", porta, "-U", usuario, 
                    "-d", banco_destino, "--no-owner", "--no-privileges", "-v", 
                    arquivo_restaurar
                ]
                
                resultado = subprocess.run(comando, env=env, capture_output=True, text=True)
                
                if resultado.returncode in [0, 1]:
                    st.success(f"Restauração finalizada para o banco '{banco_destino}'!")
                    with st.expander("Ver Logs detalhados do PostgreSQL"):
                        st.code(resultado.stderr, language="text")
                else:
                    st.error("Falha na restauração.")
                    with st.expander("Detalhes do Erro Crítico"):
                        st.code(resultado.stderr, language="text")
                    
            except Exception as e:
                st.error(f"Erro no processo de restauração: {e}")
                
#     ABA 4: AUDITORIA
with tab_audit:
    st.header(":material/history: Histórico de Auditoria")
    if st.button(":material/refresh: Atualizar Tabela"):
        try:
            conn = psycopg2.connect(host=host, port=porta, dbname=dbname, user=usuario, password=senha)
            df = pd.read_sql("SELECT * FROM auditoria_backup ORDER BY data_hora_inicio DESC;", conn)
            st.dataframe(df, use_container_width=True)
            conn.close()
        except: 
            st.warning("Nenhum registo de auditoria encontrado. Certifique-se de preencher o Host, Nome do Banco e Senha na aba 'Backup'.")