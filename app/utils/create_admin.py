import argparse
from getpass import getpass

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Company, Role, User
from app.security.auth import hash_password


def main():
    parser = argparse.ArgumentParser(description="Cria ou promove um administrador global.")
    parser.add_argument("email")
    parser.add_argument("--name", default="Administrador")
    parser.add_argument("--company", default="Administração Divulgaí IA")
    args = parser.parse_args()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(func.lower(User.email) == args.email.lower()))
        if user:
            user.role = Role.admin
            db.commit()
            print("Usuário promovido a administrador.")
            return
        password = getpass("Senha (mínimo 8 caracteres, letras e números): ")
        if len(password) < 8 or not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
            raise SystemExit("Senha inválida.")
        company = Company(name=args.company)
        db.add(company); db.flush()
        db.add(User(company_id=company.id, name=args.name, email=args.email.lower(), password_hash=hash_password(password), role=Role.admin))
        db.commit()
        print("Administrador criado.")


if __name__ == "__main__":
    main()

