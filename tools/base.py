class BaseTool:
    def __init__(self, canvas, data_manager):
        self.canvas = canvas
        self.data_manager = data_manager
        
        # 【关键】必须确保拿到的是 QtInteractor 对象
        if hasattr(canvas, 'plotter'):
            self.plotter = canvas.plotter
        else:
            print("【严重错误】BaseTool 初始化失败：Canvas 中没有 plotter 对象！")
            self.plotter = None
            
        self.observers = []

    def activate(self):
        pass

    def deactivate(self):
        self.clear_observers()

    def clear_observers(self):
        if self.plotter and getattr(self.plotter, "interactor", None):
            for obs in self.observers:
                try:
                    self.plotter.interactor.RemoveObserver(obs)
                except Exception:
                    # Ignore stale/invalid observer ids to keep tool switching stable.
                    pass
        self.observers = []
