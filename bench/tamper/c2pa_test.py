"""Signs test images with real C2PA manifests (throwaway test CA), then scans them.
Run: python bench/tamper/c2pa_test.py <out_dir>  (needs bench/tamper/clean.jpg next to out_dir parent: see README)"""
import sys, json, datetime as dt
from pathlib import Path
from cryptography import x509
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
import c2pa
d=Path(sys.argv[1]); now=dt.datetime.now(dt.timezone.utc)
def name(cn): return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,cn),x509.NameAttribute(NameOID.ORGANIZATION_NAME,"DisputeGraph Test")])
cak=ec.generate_private_key(ec.SECP256R1())
ca=(x509.CertificateBuilder().subject_name(name("Test Root CA")).issuer_name(name("Test Root CA")).public_key(cak.public_key())
    .serial_number(x509.random_serial_number()).not_valid_before(now-dt.timedelta(days=1)).not_valid_after(now+dt.timedelta(days=365))
    .add_extension(x509.BasicConstraints(ca=True,path_length=None),True)
    .add_extension(x509.KeyUsage(False,False,False,False,False,True,True,False,False),True).sign(cak,hashes.SHA256()))
k=ec.generate_private_key(ec.SECP256R1())
leaf=(x509.CertificateBuilder().subject_name(name("Test AI Image Generator")).issuer_name(ca.subject).public_key(k.public_key())
    .serial_number(x509.random_serial_number()).not_valid_before(now-dt.timedelta(days=1)).not_valid_after(now+dt.timedelta(days=365))
    .add_extension(x509.BasicConstraints(ca=False,path_length=None),True)
    .add_extension(x509.KeyUsage(True,False,False,False,False,False,False,False,False),True)
    .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]),False)
    .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(cak.public_key()),False)
    .add_extension(x509.SubjectKeyIdentifier.from_public_key(k.public_key()),False).sign(cak,hashes.SHA256()))
chain=leaf.public_bytes(serialization.Encoding.PEM)+ca.public_bytes(serialization.Encoding.PEM)
key=k.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
signer=c2pa.Signer.from_info(c2pa.C2paSignerInfo(alg=b"es256",sign_cert=chain,private_key=key,ta_url=None))
src=Path(__file__).parent/"clean.jpg"
IPTC="http://cv.iptc.org/newscodes/digitalsourcetype/"
def make(out, actions):
    m={"claim_generator_info":[{"name":"Test AI Image Generator","version":"1.0"}],"title":out,
       "assertions":[{"label":"c2pa.actions","data":{"actions":actions}}]}
    with c2pa.Builder(json.dumps(m)) as b: b.sign_file(str(src),str(d/out),signer)
make("ai_generated_c2pa.jpg",[{"action":"c2pa.created","digitalSourceType":IPTC+"trainedAlgorithmicMedia"}])
make("edited_c2pa.jpg",[{"action":"c2pa.created","digitalSourceType":IPTC+"digitalCapture"},{"action":"c2pa.edited"}])
make("camera_c2pa.jpg",[{"action":"c2pa.created","digitalSourceType":IPTC+"digitalCapture"}])
sys.path.insert(0,".")
from backend.disputegraph.tamper import scan
for n in ["ai_generated_c2pa.jpg","edited_c2pa.jpg","camera_c2pa.jpg"]:
    r=scan(d/n); print(f"{n:24} {r['verdict']:10}",[s['detail'] for s in r['signals']])
