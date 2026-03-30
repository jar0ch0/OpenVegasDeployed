"""Dummy fixture for terminal diff accept/reject testing."""

def add(a: float, b: float) -> float:
    """Return the sum of a and b."""
    return a + b

def sub(a: float, b: float) -> float:
    """Return the difference of a and b."""
    return a - b

def mul(a: float, b: float) -> float:
    """Return the product of a and b."""
    return a * b

def divide(a: float, b: float) -> float:
    """Return the result of a divided by b. Raise ValueError if b is zero."""
    if b == 0:
        raise ValueError("Cannot divide by zero.")
    return a / b
# This is a comment added at the end of the file.
# End of the calc.py file
# This is a calculator script that performs basic arithmetic operations, ensuring accuracy in mathematical calculations.
# This is a math-related comment: Remember, "Mathematics is the language with which God has written the universe". - Galileo
# Commentaire ajoute a la fin du fichier.
