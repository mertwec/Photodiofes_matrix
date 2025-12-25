from src.generator_data import genearate_random_data
from src.data_types import Point2D
import time 
from src.get_single_point import light_direction_to_point
import matplotlib.pyplot as plt


SIZE_DISPLAY = 100 # px


if __name__ == "__main__":
    # data_pd = genearate_random_data(2)
    # data_pd_zero = [[0, 1], [0, 0]]
    # data_pd_one = [[1, 1], [1, 1]]
    # data_pd_1 = [[.5, .5], [0, 0]]
    # data_pd_1_1 = [[.4, .4], [0, 0]]
    # data_pd_2 = [[.5, .5], [0.2, 0.2]]

    # data_set = [data_pd, data_pd_zero, data_pd_one, data_pd_1, data_pd_1_1, data_pd_2]
    
    # for data in data_set:
    #     point = light_direction_to_point(data, SIZE_DISPLAY)
    #     print(f"Photodiodes matrix: {data} => Light direction point: {point}")

    #     # Example usage
    # test_point = Point2D(30, 70)
    # display_light_point(test_point, size=100)

    # time.sleep(2)

    # Включаем интерактивный режим matplotlib
    # позволяет обновлять график без блокировки выполнения программы
    plt.ion()

    # Создаём фигуру и оси
    fig, ax = plt.subplots()

    # Задаём рабочее поле отображения (дисплей 100x100)
    ax.set_xlim(0, SIZE_DISPLAY)
    ax.set_ylim(0, SIZE_DISPLAY)

    # Получаем текущие границы осей
    # нужно, чтобы корректно вычислить центр
    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()

    # Рисуем вертикальную осевую линию (ось Y) через центр дисплея
    ax.axvline(
        x=(xmin + xmax) / 2,
        color='green',
        linestyle='--',
        linewidth=1
    )

    # Рисуем горизонтальную осевую линию (ось X) через центр дисплея
    ax.axhline(
        y=(ymin + ymax) / 2,
        color='green',
        linestyle='--',
        linewidth=1
    )

    # Инициализируем графический объект для одной точки
    # 'wo' — white circle (белая точка)
    line, = ax.plot([], [], 'wo')

    # Флаг управления главным циклом
    running = True

    # Обработчик нажатий клавиш
    def on_key(event):
        global running
        # При нажатии 'q' завершаем цикл и закрываем окно
        if event.key == 'q':
            running = False

    # Подключаем обработчик событий клавиатуры к canvas
    fig.canvas.mpl_connect('key_press_event', on_key)

    # Функция обновления положения точки
    def update(point):
        if point is None:
            # Если данных нет — очищаем точку
            line.set_data([], [])
        else:
            # set_data требует последовательности, даже для одной точки
            line.set_data([point.x], [point.y])

        # Запрашиваем перерисовку без немедленной блокировки
        fig.canvas.draw_idle()
        fig.canvas.flush_events()

    # Основной цикл: генерация данных и обновление отображения
    while running:
        # Генерация тестовых данных фотодиодной матрицы
        p = genearate_random_data(2)

        # Преобразование матрицы в точку направления засветки
        point = light_direction_to_point(p, SIZE_DISPLAY)

        print(f"Photodiodes matrix: {p} => Light direction point: {point}")

        # Обновляем положение точки на дисплее
        update(point)

        # Частота обновления — 1 Гц
        time.sleep(1)

    # Выключаем интерактивный режим и корректно закрываем окно
    plt.ioff()
    plt.close(fig)



