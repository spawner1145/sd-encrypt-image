
def preload(parser):
    parser.add_argument("--enc-pw", type=str, help="The password to enable image encryption.", default=None)
    parser.add_argument("--enable-webp",action="store_true",help="Enable webp format for lower network costs")
