import flet as ft

#カウンタター表示用のテキスト
def main(page: ft.Page):
    counter = ft.Text("0", size=50, data=0)

#ボタンが押しされた時呼び出され得る関数
    def increment_click(e):
        counter.data += 1
        counter.value = str(counter.data)
        counter.update()

#カウンタターを増やすボタン
    page.floating_action_button = ft.FloatingActionButton(
        icon=ft.Icons.ADD, on_click=increment_click
    )
    #safe areで囲んで、中央にカウンターを配置
    page.add(
        ft.SafeArea(
            ft.Container(
                counter,
                alignment=ft.alignment.center,
            ),
            expand=True,
        )
    )


ft.app(main)
