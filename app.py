import numpy as np
import pandas as pd

# 1. Carga dos dados
df = pd.read_excel('dados_frete.xlsx')

# 2. Padronização dos textos (remove espaços e garante maiúsculas)
df['UF_ORIGEM'] = df['UF_ORIGEM'].astype(str).str.strip().str.upper()
df['UF_DESTINO'] = df['UF_DESTINO'].astype(str).str.strip().str.upper()

# 3. Tratamento dos valores (converte strings formatadas para float para evitar erro no cálculo)
df['VALOR_FRETE_PRATICADO'] = pd.to_numeric(
    df['VALOR_FRETE_PRATICADO']
    .astype(str)
    .str.replace('R$', '', regex=False)
    .str.replace('.', '', regex=False)
    .str.replace(',', '.', regex=False)
    .str.strip(),
    errors='coerce',
)

df['VALOR_FRETE_MINIMO'] = pd.to_numeric(
    df['VALOR_FRETE_MINIMO']
    .astype(str)
    .str.replace('R$', '', regex=False)
    .str.replace('.', '', regex=False)
    .str.replace(',', '.', regex=False)
    .str.strip(),
    errors='coerce',
)

# 4. Regra de validação do frete
# Tolerância pequena para evitar divergências por arredondamento de centavos
tol = 0.01

df['STATUS_FRETE'] = np.select(
    [
        df['VALOR_FRETE_PRATICADO'] < (df['VALOR_FRETE_MINIMO'] - tol),
        df['VALOR_FRETE_PRATICADO'] >= (df['VALOR_FRETE_MINIMO'] - tol),
    ],
    ['Abaixo do Mínimo', 'Dentro do Mínimo'],
    default='Não Identificado',
)

# 5. Agrupamento por rota
resumo_rotas = (
    df.groupby(['UF_ORIGEM', 'UF_DESTINO'])
    .agg(
        total_rotas=('STATUS_FRETE', 'count'),
        rotas_abaixo=(
            'STATUS_FRETE',
            lambda x: (x == 'Abaixo do Mínimo').sum(),
        ),
        rotas_dentro=(
            'STATUS_FRETE',
            lambda x: (x == 'Dentro do Mínimo').sum(),
        ),
        nao_identificadas=(
            'STATUS_FRETE',
            lambda x: (x == 'Não Identificado').sum(),
        ),
    )
    .reset_index()
)

# Exportação do resultado
resumo_rotas.to_excel('relatorio_rotas_atualizado.xlsx', index=False)
