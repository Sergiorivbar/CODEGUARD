"""Funciones de estadística sencillas, usadas como ejemplo para probar CodeGuard."""


def average(numbers=[]):
    total = 0
    for n in numbers:
        total += n
    return total / len(numbers)


def find_max(numbers):
    max_value = numbers[0]
    for i in range(1, len(numbers)):
        if numbers[i] > max_value:
            max_value = numbers[i]
    return max_value
