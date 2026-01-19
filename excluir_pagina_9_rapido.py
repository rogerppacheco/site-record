from crm_app.models import RecordApoia

arquivos = RecordApoia.objects.filter(nome_original__icontains='pagina_9.jpg')
print(f"Encontrados {arquivos.count()} arquivo(s):")
for arq in arquivos:
    print(f"ID: {arq.id}, Titulo: {arq.titulo}, Nome: {arq.nome_original}, Tipo: {arq.tipo_arquivo}, Ativo: {arq.ativo}")

if arquivos.exists():
    for arq in arquivos:
        arq.ativo = False
        arq.save()
        print(f"Arquivo ID {arq.id} marcado como inativo")
    print(f"{arquivos.count()} arquivo(s) excluido(s) com sucesso!")
else:
    print("Nenhum arquivo encontrado.")
