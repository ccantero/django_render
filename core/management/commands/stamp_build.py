from django.core.management.base import BaseCommand

from django_render.version import BUILD_STAMP_PATH, write_build_stamp


class Command(BaseCommand):
    help = (
        "Write build_info.json with the current UTC time. "
        "Append this to the Render Build Command when an exact build time "
        "should appear in the footer and at /version/."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default="",
            help="Stamp file to write. Defaults to build_info.json in the repository root.",
        )

    def handle(self, *args, **options):
        path = options["path"] or BUILD_STAMP_PATH
        moment = write_build_stamp(path)
        self.stdout.write(f"Wrote build stamp {moment.strftime('%Y-%m-%dT%H:%M:%SZ')} to {path}")
