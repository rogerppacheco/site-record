from django.core.management.base import BaseCommand
from crm_app.models import RecordApoia


class Command(BaseCommand):
    help = 'Exclui arquivo pagina_9.jpg do RecordApoia'

    def add_arguments(self, parser):
        parser.add_argument(
            '--remover',
            action='store_true',
            help='Remove diretamente sem confirmação interativa',
        )

    def handle(self, *args, **options):
        self.stdout.write("=" * 60)
        self.stdout.write("SCRIPT DE EXCLUSÃO - pagina_9.jpg")
        self.stdout.write("=" * 60)
        
        arquivos = RecordApoia.objects.filter(nome_original__icontains='pagina_9.jpg')
        
        if not arquivos.exists():
            self.stdout.write(self.style.WARNING("❌ Nenhum arquivo 'pagina_9.jpg' encontrado."))
            return
        
        self.stdout.write(f"\n🔍 Encontrados {arquivos.count()} arquivo(s):")
        for arq in arquivos:
            self.stdout.write(f"  - ID: {arq.id}")
            self.stdout.write(f"    Título: {arq.titulo}")
            self.stdout.write(f"    Nome Original: {arq.nome_original}")
            self.stdout.write(f"    Tipo: {arq.tipo_arquivo}")
            self.stdout.write(f"    Ativo: {arq.ativo}")
            self.stdout.write("")
        
        if options['remover']:
            confirmacao = 'SIM'
        else:
            confirmacao = input(f"Deseja excluir {arquivos.count()} arquivo(s)? (digite 'SIM' para confirmar): ").strip().upper()
        
        if confirmacao != 'SIM':
            self.stdout.write(self.style.ERROR("❌ Operação cancelada."))
            return
        
        # Soft delete (marcar como inativo)
        for arq in arquivos:
            arq.ativo = False
            arq.save()
            self.stdout.write(self.style.SUCCESS(f"✅ Arquivo ID {arq.id} ({arq.titulo}) marcado como inativo."))
        
        self.stdout.write(self.style.SUCCESS(f"\n✅ {arquivos.count()} arquivo(s) excluído(s) com sucesso!"))
