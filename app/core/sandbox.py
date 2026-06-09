import ast
import traceback


class PythonSandbox:
    def verify_code(self, code_string: str) -> tuple[bool, str]:
        try:
            ast.parse(code_string)
        except SyntaxError as exc:
            line = (exc.text or "").strip()
            lineno = exc.lineno or 0
            offset = exc.offset or 0
            detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            return (
                False,
                f"Syntax Error: line {lineno}, offset {offset}: {exc.msg}\n{line}\n{detail}",
            )
        return True, "Success"
