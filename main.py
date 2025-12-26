from src.display import display_single_light_point
from src.generator_data import genearate_random_data
from src.data_types import Point2D
import time 
from src.get_single_point import light_direction_to_point, light_direction_to_point_univ
import matplotlib.pyplot as plt


SIZE_DISPLAY = 200 # px


if __name__ == "__main__":
    data_pd = genearate_random_data(2)
    data_pd_zero = [[0, 0], [0, 0]]
    data_pd_left_top = [[1, 0], [0, 0]]
    data_pd_left = [[1, 0], [1, 0]]
    data_pd_right = [[0, 1], [0, 1]]
    data_pd_bottom = [[0, 0], [1, 1]]
    data_pd_one = [[1, 1], [1, 1]]
    data_pd_1 = [[.1, .1], [0.3, 0.7]]
    data_pd_2 = [[.5, .5], [0.2, 0.2]]

    data_set = [data_pd, data_pd_zero, data_pd_left_top, data_pd_left, data_pd_right,
        data_pd_bottom, data_pd_one, data_pd_1, data_pd_2]
    
    # for data in data_set:
    #     point = light_direction_to_point(data, SIZE_DISPLAY)
    #     print(f"Photodiodes matrix: {data} => Light direction point: {point}")    
    #     display_single_light_point(point, size=SIZE_DISPLAY)


    # ============================================================

    # Включаем интерактивный режим matplotlib
    # позволяет обновлять график без блокировки выполнения программы
    plt.ion()
    plt.style.use('dark_background')

    # Создаём фигуру и оси
    fig, ax = plt.subplots()
   
    SIZE_DISPLAY+=10
    # Задаём рабочее поле отображения (дисплей 100x100)
    ax.set_xlim(-SIZE_DISPLAY/2, SIZE_DISPLAY/2)
    ax.set_ylim(-SIZE_DISPLAY/2, SIZE_DISPLAY/2)

    # Получаем текущие границы осей
    # нужно, чтобы корректно вычислить центр
    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()

    # Рисуем вертикальную осевую линию (ось Y) через центр дисплея
    ax.axvline(
        x=0,
        color='green',
        linestyle='--',
        linewidth=1
    )

    # Рисуем горизонтальную осевую линию (ось X) через центр дисплея
    ax.axhline(
        y=0,
        color='green',
        linestyle='--',
        linewidth=1
    )

    # Текстовое поле для отображения статуса (нет данных)
    status_text = ax.text(
            10, 10,
            "No Light Detected",
            color='red',
            fontsize=10,
            visible=False   # изначально скрыт
        )
    
    # Текстовое поле для отображения координат точки
    point_label = ax.text(
        0, 0, "",
        color='white',
        fontsize=8,
        ha='left',
        va='bottom',
        visible=False
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
    def update(point: Point2D | None):
        if point is None:
            # Если данных нет — очищаем точку
            line.set_data([], [])
            point_label.set_visible(False)
            status_text.set_visible(True)
        else:
            # set_data требует последовательности, даже для одной точки
            line.set_data([point.x], [point.y])

            point_label.set_position((point.x + 1, point.y + 1))  # смещение, чтобы не перекрывать точку
            point_label.set_text(f"({point.x:.1f}, {point.y:.1f})")
            point_label.set_visible(True)
            status_text.set_visible(False)

        # Запрашиваем перерисовку без немедленной блокировки
        fig.canvas.draw_idle()
        fig.canvas.flush_events()

    # Основной цикл: генерация данных и обновление отображения
    while running and data_set:
        # Генерация тестовых данных фотодиодной матрицы
        p = genearate_random_data(4)
        # p = data_set.pop(0)

        # Преобразование матрицы в точку направления засветки
        point = light_direction_to_point_univ(p, SIZE_DISPLAY-10)
        print(f"Photodiodes matrix: {p} => Light direction point: {point}")

        # Обновляем положение точки на дисплее
        update(point)

        # Частота обновления — 1 Гц
        time.sleep(1)

    # Выключаем интерактивный режим и корректно закрываем окно
    plt.ioff()
    plt.close(fig)
