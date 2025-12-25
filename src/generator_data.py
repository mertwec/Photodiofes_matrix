import random
from pprint import pprint


def genearate_random_data(dimension:int = 2) -> list[list[float]]:
    """
    generates a random matrix of photodiodes with values 0 or 1.
    
    param:
    dimension (int): Dimension of the photodiodes matrix (2x2 or 4x4).

    Returns:
    list: List of lists, representing the photodiodes matrix with random values 0 or 1.
    """

    return [[random.random() for _ in range(dimension)] for _ in range(dimension)]


if __name__ == "__main__":
    data_phd_2x2 = genearate_random_data(2)
    data_phd_4x4 = genearate_random_data(4)

    print("Generated 2x2 photodiodes matrix:")
    pprint(data_phd_2x2)

    print("\nGenerated 4x4 photodiodes matrix:")
    pprint(data_phd_4x4)