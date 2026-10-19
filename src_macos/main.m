#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>
#import <signal.h>
#import <sys/socket.h>
#import <netinet/in.h>
#import <arpa/inet.h>
#import <unistd.h>

@interface AppDelegate : NSObject <NSApplicationDelegate, WKNavigationDelegate, NSWindowDelegate>
@property (strong, nonatomic) NSWindow *window;
@property (strong, nonatomic) WKWebView *webView;
@property (strong, nonatomic) NSView *loadingView;
@property (strong, nonatomic) NSProgressIndicator *spinner;
@property (strong, nonatomic) NSTextField *statusLabel;
@property (strong, nonatomic) NSTask *serverTask;
@property (assign, nonatomic) NSInteger serverPort;
@property (strong, nonatomic) NSTimer *pollTimer;
@property (assign, nonatomic) NSInteger retryCount;
@end

@implementation AppDelegate

- (void)applicationDidFinishLaunching:(NSNotification *)aNotification {
    self.serverPort = 8765;
    self.retryCount = 0;

    // 1. Setup native macOS Menu bar
    [self setupMenuBar];

    // 2. Setup native NSWindow
    NSRect screenRect = [[NSScreen mainScreen] visibleFrame];
    CGFloat width = MIN(1380, screenRect.size.width - 80);
    CGFloat height = MIN(920, screenRect.size.height - 80);
    CGFloat x = screenRect.origin.x + (screenRect.size.width - width) / 2.0;
    CGFloat y = screenRect.origin.y + (screenRect.size.height - height) / 2.0;
    NSRect windowRect = NSMakeRect(x, y, width, height);

    NSWindowStyleMask style = NSWindowStyleMaskTitled |
                              NSWindowStyleMaskClosable |
                              NSWindowStyleMaskMiniaturizable |
                              NSWindowStyleMaskResizable;

    self.window = [[NSWindow alloc] initWithContentRect:windowRect
                                              styleMask:style
                                                backing:NSBackingStoreBuffered
                                                  defer:NO];

    [self.window setTitle:@"AOUL — AI Robotics Copilot (Actuator, Orientation, Undefined-behavior, Locator)"];
    [self.window setMinSize:NSMakeSize(1024, 680)];
    [self.window setAppearance:[NSAppearance appearanceNamed:NSAppearanceNameDarkAqua]];
    [self.window setBackgroundColor:[NSColor colorWithCalibratedRed:11.0/255.0 green:15.0/255.0 blue:25.0/255.0 alpha:1.0]];
    [self.window setDelegate:self];

    // 3. Setup WKWebView with developer tools and modern configuration
    WKWebViewConfiguration *config = [[WKWebViewConfiguration alloc] init];
    config.defaultWebpagePreferences.allowsContentJavaScript = YES;
    [config.preferences setValue:@YES forKey:@"developerExtrasEnabled"];
    config.applicationNameForUserAgent = @"AOUL/2.0 Native macOS App";

    self.webView = [[WKWebView alloc] initWithFrame:self.window.contentView.bounds configuration:config];
    self.webView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.webView.navigationDelegate = self;
    self.webView.alphaValue = 0.0;
    [self.window.contentView addSubview:self.webView];

    // 4. Setup Native Loading / Splash View
    self.loadingView = [[NSView alloc] initWithFrame:self.window.contentView.bounds];
    self.loadingView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.loadingView.wantsLayer = YES;
    self.loadingView.layer.backgroundColor = [NSColor colorWithCalibratedRed:11.0/255.0 green:15.0/255.0 blue:25.0/255.0 alpha:1.0].CGColor;

    self.spinner = [[NSProgressIndicator alloc] initWithFrame:NSMakeRect((width - 36)/2.0, (height/2.0) + 15, 36, 36)];
    self.spinner.style = NSProgressIndicatorStyleSpinning;
    self.spinner.controlSize = NSControlSizeRegular;
    [self.spinner startAnimation:nil];
    [self.loadingView addSubview:self.spinner];

    self.statusLabel = [[NSTextField alloc] initWithFrame:NSMakeRect((width - 500)/2.0, (height/2.0) - 45, 500, 30)];
    self.statusLabel.stringValue = @"Starting AOUL Robotics Engine & Qwen...";
    self.statusLabel.alignment = NSTextAlignmentCenter;
    self.statusLabel.textColor = [NSColor colorWithCalibratedRed:56.0/255.0 green:189.0/255.0 blue:248.0/255.0 alpha:1.0];
    self.statusLabel.font = [NSFont systemFontOfSize:13 weight:NSFontWeightMedium];
    self.statusLabel.editable = NO;
    self.statusLabel.bordered = NO;
    self.statusLabel.backgroundColor = [NSColor clearColor];
    [self.loadingView addSubview:self.statusLabel];

    [self.window.contentView addSubview:self.loadingView];

    [self.window makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];

    // 5. Ensure Ollama service is active
    [self ensureOllamaRunning];

    // 6. Launch or connect to local AOUL server
    [self startServerIfNeeded];
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender {
    return YES;
}

- (BOOL)windowShouldClose:(NSWindow *)sender {
    [NSApp terminate:nil];
    return YES;
}

- (void)applicationWillTerminate:(NSNotification *)aNotification {
    if (self.serverTask && [self.serverTask isRunning]) {
        [self.serverTask terminate];
    }
}

#pragma mark - Server & Ollama Lifecycle

- (BOOL)isPortOpen:(NSInteger)port {
    int sock = socket(AF_INET, SOCK_STREAM, 0);
    if (sock < 0) return NO;

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons((uint16_t)port);
    inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);

    struct timeval tv;
    tv.tv_sec = 0;
    tv.tv_usec = 250000; // 250ms timeout
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

    int res = connect(sock, (struct sockaddr *)&addr, sizeof(addr));
    close(sock);
    return (res == 0);
}

- (void)ensureOllamaRunning {
    dispatch_async(dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_LOW, 0), ^{
        if (![self isPortOpen:11434]) {
            NSString *home = NSHomeDirectory();
            NSString *plist = [home stringByAppendingPathComponent:@"Library/LaunchAgents/com.ollama.serve.plist"];
            if ([[NSFileManager defaultManager] fileExistsAtPath:plist]) {
                NSTask *t = [[NSTask alloc] init];
                t.launchPath = @"/bin/launchctl";
                t.arguments = @[@"load", plist];
                @try { [t launch]; } @catch (NSException *e) {}
            }
            if (![self isPortOpen:11434]) {
                if ([[NSFileManager defaultManager] isExecutableFileAtPath:@"/usr/local/bin/ollama"]) {
                    NSTask *t2 = [[NSTask alloc] init];
                    t2.launchPath = @"/usr/local/bin/ollama";
                    t2.arguments = @[@"serve"];
                    @try { [t2 launch]; } @catch (NSException *e) {}
                }
            }
        }
    });
}

- (NSString *)findPythonBinary {
    NSArray *candidates = @[
        @"/Library/Frameworks/Python.framework/Versions/Current/bin/python3",
        @"/Library/Frameworks/Python.framework/Versions/3.13/bin/python3",
        @"/opt/homebrew/bin/python3",
        @"/usr/local/bin/python3",
        @"/usr/bin/python3"
    ];

    for (NSString *path in candidates) {
        if ([[NSFileManager defaultManager] isExecutableFileAtPath:path]) {
            return path;
        }
    }
    return @"/usr/bin/python3";
}

- (NSString *)resolveProjectDirectory {
    NSString *liveWorkspace = @"/Users/apple/.gemini/antigravity/scratch/robosage";
    if ([[NSFileManager defaultManager] fileExistsAtPath:[liveWorkspace stringByAppendingPathComponent:@"run.py"]]) {
        return liveWorkspace;
    }

    NSString *bundleRes = [[[NSBundle mainBundle] resourcePath] stringByAppendingPathComponent:@"robosage"];
    if ([[NSFileManager defaultManager] fileExistsAtPath:[bundleRes stringByAppendingPathComponent:@"run.py"]]) {
        return bundleRes;
    }

    return liveWorkspace;
}

- (void)startServerIfNeeded {
    if ([self isPortOpen:self.serverPort]) {
        [self loadAppURL];
        return;
    }

    NSString *pythonBin = [self findPythonBinary];
    NSString *projectDir = [self resolveProjectDirectory];
    NSString *runScript = [projectDir stringByAppendingPathComponent:@"run.py"];

    NSString *logDir = [NSHomeDirectory() stringByAppendingPathComponent:@"Library/Logs/AOUL"];
    [[NSFileManager defaultManager] createDirectoryAtPath:logDir withIntermediateDirectories:YES attributes:nil error:nil];
    NSString *logPath = [logDir stringByAppendingPathComponent:@"server.log"];
    [[NSFileManager defaultManager] createFileAtPath:logPath contents:nil attributes:nil];
    NSFileHandle *logHandle = [NSFileHandle fileHandleForWritingAtPath:logPath];

    self.serverTask = [[NSTask alloc] init];
    self.serverTask.launchPath = pythonBin;
    self.serverTask.arguments = @[runScript, @"--no-browser", @"--port", [NSString stringWithFormat:@"%ld", (long)self.serverPort]];
    self.serverTask.currentDirectoryPath = projectDir;

    if (logHandle) {
        self.serverTask.standardOutput = logHandle;
        self.serverTask.standardError = logHandle;
    }

    @try {
        [self.serverTask launch];
    } @catch (NSException *e) {
        self.statusLabel.stringValue = [NSString stringWithFormat:@"Failed to launch server: %@", e.reason];
        self.statusLabel.textColor = [NSColor colorWithCalibratedRed:239.0/255.0 green:68.0/255.0 blue:68.0/255.0 alpha:1.0];
        return;
    }

    // Start polling for server readiness
    self.pollTimer = [NSTimer scheduledTimerWithTimeInterval:0.15
                                                      target:self
                                                    selector:@selector(checkServerReady:)
                                                    userInfo:nil
                                                     repeats:YES];
}

- (void)checkServerReady:(NSTimer *)timer {
    self.retryCount++;
    if ([self isPortOpen:self.serverPort]) {
        [self.pollTimer invalidate];
        self.pollTimer = nil;
        [self loadAppURL];
    } else if (self.retryCount > 60) { // 9 seconds
        [self.pollTimer invalidate];
        self.pollTimer = nil;
        self.statusLabel.stringValue = @"Server startup taking longer than expected. Retrying...";
        [self loadAppURL]; // Attempt load anyway
    }
}

- (void)loadAppURL {
    self.statusLabel.stringValue = @"Loading Robotics Workspace...";
    NSURL *url = [NSURL URLWithString:[NSString stringWithFormat:@"http://127.0.0.1:%ld/", (long)self.serverPort]];
    NSURLRequest *req = [NSURLRequest requestWithURL:url
                                         cachePolicy:NSURLRequestReloadIgnoringLocalCacheData
                                     timeoutInterval:30.0];
    [self.webView loadRequest:req];
}

#pragma mark - WKNavigationDelegate

- (void)webView:(WKWebView *)webView didFinishNavigation:(WKNavigation *)navigation {
    [NSAnimationContext runAnimationGroup:^(NSAnimationContext *context) {
        context.duration = 0.3;
        self.webView.animator.alphaValue = 1.0;
        self.loadingView.animator.alphaValue = 0.0;
    } completionHandler:^{
        [self.spinner stopAnimation:nil];
        [self.loadingView removeFromSuperview];
    }];
}

- (void)webView:(WKWebView *)webView didFailProvisionalNavigation:(WKNavigation *)navigation withError:(NSError *)error {
    // If connection refused, retry loading after short delay
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.3 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
        [self loadAppURL];
    });
}

- (void)webView:(WKWebView *)webView decidePolicyForNavigationAction:(WKNavigationAction *)navigationAction decisionHandler:(void (^)(WKNavigationActionPolicy))decisionHandler {
    NSURL *url = navigationAction.request.URL;
    NSString *host = url.host;

    // Keep localhost inside the native app window
    if ([host isEqualToString:@"127.0.0.1"] || [host isEqualToString:@"localhost"] || [url.scheme isEqualToString:@"blob"]) {
        decisionHandler(WKNavigationActionPolicyAllow);
    } else if ([url.scheme isEqualToString:@"http"] || [url.scheme isEqualToString:@"https"]) {
        // Open external links (ROS 2 docs, external tools) in default browser
        [[NSWorkspace sharedWorkspace] openURL:url];
        decisionHandler(WKNavigationActionPolicyCancel);
    } else {
        decisionHandler(WKNavigationActionPolicyAllow);
    }
}

#pragma mark - Native macOS Menu Bar

- (void)setupMenuBar {
    NSMenu *mainMenu = [[NSMenu alloc] init];

    // 1. AOUL App Menu
    NSMenuItem *appMenuItem = [[NSMenuItem alloc] init];
    NSMenu *appMenu = [[NSMenu alloc] initWithTitle:@"AOUL"];
    [appMenu addItemWithTitle:@"About AOUL" action:@selector(showAbout) keyEquivalent:@""];
    [appMenu addItem:[NSMenuItem separatorItem]];
    [appMenu addItemWithTitle:@"Hide AOUL" action:@selector(hide:) keyEquivalent:@"h"];
    NSMenuItem *hideOthers = [appMenu addItemWithTitle:@"Hide Others" action:@selector(hideOtherApplications:) keyEquivalent:@"h"];
    [hideOthers setKeyEquivalentModifierMask:(NSEventModifierFlagOption | NSEventModifierFlagCommand)];
    [appMenu addItemWithTitle:@"Show All" action:@selector(unhideAllApplications:) keyEquivalent:@""];
    [appMenu addItem:[NSMenuItem separatorItem]];
    [appMenu addItemWithTitle:@"Quit AOUL" action:@selector(terminate:) keyEquivalent:@"q"];
    [appMenuItem setSubmenu:appMenu];
    [mainMenu addItem:appMenuItem];

    // 2. Edit Menu (Critical for code copy, paste, select-all, undo)
    NSMenuItem *editMenuItem = [[NSMenuItem alloc] init];
    NSMenu *editMenu = [[NSMenu alloc] initWithTitle:@"Edit"];
    [editMenu addItemWithTitle:@"Undo" action:@selector(undo:) keyEquivalent:@"z"];
    NSMenuItem *redoItem = [editMenu addItemWithTitle:@"Redo" action:@selector(redo:) keyEquivalent:@"z"];
    [redoItem setKeyEquivalentModifierMask:(NSEventModifierFlagShift | NSEventModifierFlagCommand)];
    [editMenu addItem:[NSMenuItem separatorItem]];
    [editMenu addItemWithTitle:@"Cut" action:@selector(cut:) keyEquivalent:@"x"];
    [editMenu addItemWithTitle:@"Copy" action:@selector(copy:) keyEquivalent:@"c"];
    [editMenu addItemWithTitle:@"Paste" action:@selector(paste:) keyEquivalent:@"v"];
    [editMenu addItemWithTitle:@"Select All" action:@selector(selectAll:) keyEquivalent:@"a"];
    [editMenuItem setSubmenu:editMenu];
    [mainMenu addItem:editMenuItem];

    // 3. View Menu
    NSMenuItem *viewMenuItem = [[NSMenuItem alloc] init];
    NSMenu *viewMenu = [[NSMenu alloc] initWithTitle:@"View"];
    [viewMenu addItemWithTitle:@"Reload" action:@selector(reloadPage) keyEquivalent:@"r"];
    NSMenuItem *hardReload = [viewMenu addItemWithTitle:@"Force Reload" action:@selector(forceReloadPage) keyEquivalent:@"r"];
    [hardReload setKeyEquivalentModifierMask:(NSEventModifierFlagShift | NSEventModifierFlagCommand)];
    [viewMenu addItem:[NSMenuItem separatorItem]];
    [viewMenu addItemWithTitle:@"Toggle Full Screen" action:@selector(toggleFullScreen:) keyEquivalent:@"f"];
    [viewMenuItem setSubmenu:viewMenu];
    [mainMenu addItem:viewMenuItem];

    // 4. Window Menu
    NSMenuItem *windowMenuItem = [[NSMenuItem alloc] init];
    NSMenu *windowMenu = [[NSMenu alloc] initWithTitle:@"Window"];
    [windowMenu addItemWithTitle:@"Minimize" action:@selector(performMiniaturize:) keyEquivalent:@"m"];
    [windowMenu addItemWithTitle:@"Zoom" action:@selector(performZoom:) keyEquivalent:@""];
    [windowMenu addItem:[NSMenuItem separatorItem]];
    [windowMenu addItemWithTitle:@"Bring All to Front" action:@selector(arrangeInFront:) keyEquivalent:@""];
    [windowMenuItem setSubmenu:windowMenu];
    [mainMenu addItem:windowMenuItem];

    // 5. Help Menu
    NSMenuItem *helpMenuItem = [[NSMenuItem alloc] init];
    NSMenu *helpMenu = [[NSMenu alloc] initWithTitle:@"Help"];
    [helpMenu addItemWithTitle:@"ROS 2 Documentation" action:@selector(openROSDocs) keyEquivalent:@""];
    [helpMenu addItemWithTitle:@"Ollama Documentation" action:@selector(openOllamaDocs) keyEquivalent:@""];
    [helpMenuItem setSubmenu:helpMenu];
    [mainMenu addItem:helpMenuItem];

    [NSApp setMainMenu:mainMenu];
}

- (void)reloadPage {
    [self.webView reload];
}

- (void)forceReloadPage {
    [self.webView reloadFromOrigin];
}

- (void)showAbout {
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"AOUL — AI Robotics Copilot";
    alert.informativeText = @"Version 2.0.0 (Native Desktop App)\n\n"
                            "Actuator • Orientation • Undefined-behavior • Locator\n\n"
                            "Autonomous Robotics Assistant & Code Optimizer powered by local Qwen Coder.\n"
                            "ROS 2 Concurrency, Safety Loopholes, QoS Analysis, and Log Triage.\n\n"
                            "© 2026 AOUL. All Rights Reserved.";
    alert.alertStyle = NSAlertStyleInformational;
    [alert runModal];
}

- (void)openROSDocs {
    [[NSWorkspace sharedWorkspace] openURL:[NSURL URLWithString:@"https://docs.ros.org/"]];
}

- (void)openOllamaDocs {
    [[NSWorkspace sharedWorkspace] openURL:[NSURL URLWithString:@"https://ollama.com/"]];
}

@end

int main(int argc, const char * argv[]) {
    @autoreleasepool {
        NSApplication *app = [NSApplication sharedApplication];
        AppDelegate *delegate = [[AppDelegate alloc] init];
        app.delegate = delegate;
        [app setActivationPolicy:NSApplicationActivationPolicyRegular];
        [app run];
    }
    return 0;
}
